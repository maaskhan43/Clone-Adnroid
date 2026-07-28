package com.clonecast.app.data

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.dataStore by preferencesDataStore(name = "settings")

object SettingsStore {
    private val API_KEY = stringPreferencesKey("api_key")
    private val PROVIDER = stringPreferencesKey("provider")
    private val GROQ_KEY = stringPreferencesKey("groq_key")
    private val COLAB_LINK = stringPreferencesKey("colab_link")

    const val PROVIDER_FISH = "fish"
    const val PROVIDER_ELEVENLABS = "elevenlabs"

    fun apiKeyFlow(context: Context): Flow<String> =
        context.dataStore.data.map { it[API_KEY] ?: "" }

    fun providerFlow(context: Context): Flow<String> =
        context.dataStore.data.map { it[PROVIDER] ?: PROVIDER_FISH }

    fun groqKeyFlow(context: Context): Flow<String> =
        context.dataStore.data.map { it[GROQ_KEY] ?: "" }

    fun colabLinkFlow(context: Context): Flow<String> =
        context.dataStore.data.map { it[COLAB_LINK] ?: "" }

    suspend fun saveColabLink(context: Context, link: String) {
        context.dataStore.edit { it[COLAB_LINK] = link }
    }

    suspend fun save(context: Context, apiKey: String, provider: String, groqKey: String) {
        context.dataStore.edit {
            it[API_KEY] = apiKey
            it[PROVIDER] = provider
            it[GROQ_KEY] = groqKey
        }
    }
}
