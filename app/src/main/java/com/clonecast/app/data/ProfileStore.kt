package com.clonecast.app.data

import android.content.Context
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json

private val Context.profileDataStore by preferencesDataStore(name = "profiles")

object ProfileStore {
    private val PROFILES = stringPreferencesKey("profiles_json")
    private val json = Json { ignoreUnknownKeys = true }
    private val listSerializer = ListSerializer(VoiceProfile.serializer())

    private fun decode(prefs: Preferences): List<VoiceProfile> =
        prefs[PROFILES]?.let { raw ->
            runCatching { json.decodeFromString(listSerializer, raw) }.getOrDefault(emptyList())
        } ?: emptyList()

    fun profilesFlow(context: Context): Flow<List<VoiceProfile>> =
        context.profileDataStore.data.map(::decode)

    suspend fun upsert(context: Context, profile: VoiceProfile) {
        context.profileDataStore.edit { prefs ->
            val current = decode(prefs)
            val updated =
                if (current.any { it.id == profile.id }) {
                    current.map { if (it.id == profile.id) profile else it }
                } else {
                    current + profile
                }
            prefs[PROFILES] = json.encodeToString(listSerializer, updated)
        }
    }

    suspend fun delete(context: Context, id: String) {
        context.profileDataStore.edit { prefs ->
            prefs[PROFILES] =
                json.encodeToString(listSerializer, decode(prefs).filterNot { it.id == id })
        }
    }
}
