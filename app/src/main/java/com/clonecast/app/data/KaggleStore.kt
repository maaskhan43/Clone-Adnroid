package com.clonecast.app.data

import android.content.Context
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json

private val Context.kaggleDataStore by preferencesDataStore(name = "kaggle")

/** Stages of one conversion job. Persisted so the app can resume after being killed. */
enum class ConvertStage {
    UPLOADING,        // blob upload + dataset version of input audio
    WAITING_DATASET,  // poll dataset status until READY
    PUSHING,          // push converter kernel
    RUNNING,          // poll kernel status (covers Kaggle QUEUED + RUNNING)
    DOWNLOADING,      // fetch output.mp3 + job_result.json
    SAVING,           // write to MediaStore
    DONE,
    ERROR,
    CANCELED;

    val isTerminal: Boolean get() = this == DONE || this == ERROR || this == CANCELED
}

@Serializable
data class ConvertJob(
    val runId: String,
    val title: String,
    /** Copy of the input inside filesDir/convert/ — survives picker permission loss. */
    val inputPath: String,
    val inputSha256: String,
    val inputDurationMs: Long,
    val stage: ConvertStage = ConvertStage.UPLOADING,
    val kaggleUser: String,
    val error: String? = null,
    val outputUri: String? = null,
    val kaggleStatus: String? = null,
    val createdAt: Long,
    val updatedAt: Long,
)

object KaggleStore {
    private val USERNAME = stringPreferencesKey("kaggle_username")
    private val API_KEY_ENC = stringPreferencesKey("kaggle_api_key_enc")
    private val JOBS = stringPreferencesKey("convert_jobs_json")
    private val BOOTSTRAPPED = stringPreferencesKey("bootstrapped_accounts_json")

    private val json = Json { ignoreUnknownKeys = true }
    private val jobsSerializer = ListSerializer(ConvertJob.serializer())
    private val accountsSerializer = ListSerializer(String.serializer())

    // --- Credentials (key encrypted via Android Keystore, see KeyCrypto) ---

    fun usernameFlow(context: Context): Flow<String> =
        context.kaggleDataStore.data.map { it[USERNAME] ?: "" }

    fun apiKeyFlow(context: Context): Flow<String> =
        context.kaggleDataStore.data.map { KeyCrypto.decrypt(it[API_KEY_ENC] ?: "") }

    suspend fun saveCreds(context: Context, username: String, apiKey: String) {
        context.kaggleDataStore.edit {
            it[USERNAME] = username.trim()
            it[API_KEY_ENC] = KeyCrypto.encrypt(apiKey.trim())
        }
    }

    // --- Job records (newest first) ---

    private fun decodeJobs(prefs: Preferences): List<ConvertJob> =
        prefs[JOBS]?.let { raw ->
            runCatching { json.decodeFromString(jobsSerializer, raw) }.getOrDefault(emptyList())
        } ?: emptyList()

    fun jobsFlow(context: Context): Flow<List<ConvertJob>> =
        context.kaggleDataStore.data.map(::decodeJobs)

    suspend fun currentJobs(context: Context): List<ConvertJob> =
        decodeJobs(context.kaggleDataStore.data.first())

    suspend fun upsertJob(context: Context, job: ConvertJob) {
        context.kaggleDataStore.edit { prefs ->
            val current = decodeJobs(prefs)
            val updated =
                if (current.any { it.runId == job.runId }) {
                    current.map { if (it.runId == job.runId) job else it }
                } else {
                    listOf(job) + current
                }
            // Keep history bounded.
            prefs[JOBS] = json.encodeToString(jobsSerializer, updated.take(30))
        }
    }

    // --- Bootstrap state: which Kaggle accounts already have the kernel pushed ---

    private fun decodeAccounts(prefs: Preferences): List<String> =
        prefs[BOOTSTRAPPED]?.let { raw ->
            runCatching { json.decodeFromString(accountsSerializer, raw) }.getOrDefault(emptyList())
        } ?: emptyList()

    suspend fun isBootstrapped(context: Context, username: String): Boolean =
        username in decodeAccounts(context.kaggleDataStore.data.first())

    suspend fun markBootstrapped(context: Context, username: String) {
        context.kaggleDataStore.edit { prefs ->
            val accounts = decodeAccounts(prefs)
            if (username !in accounts) {
                prefs[BOOTSTRAPPED] =
                    json.encodeToString(accountsSerializer, accounts + username)
            }
        }
    }
}
