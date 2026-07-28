package com.clonecast.app.tts

import com.clonecast.app.data.SettingsStore
import okhttp3.OkHttpClient
import java.io.File
import java.util.concurrent.TimeUnit

interface TtsProvider {
    val displayName: String

    /** Returns a human-readable success message, or failure with a human-readable reason. */
    suspend fun checkConnection(apiKey: String): Result<String>

    /** Uploads a voice sample and returns the provider's voice ID for the clone. */
    suspend fun cloneVoice(apiKey: String, name: String, sampleFile: File): Result<String>

    /** Generates speech for [text] with the cloned voice and returns MP3 bytes. */
    suspend fun generate(apiKey: String, voiceId: String, text: String): Result<ByteArray>
}

object Http {
    val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(180, TimeUnit.SECONDS)
        .writeTimeout(180, TimeUnit.SECONDS)
        .build()
}

fun providerFor(id: String): TtsProvider = when (id) {
    SettingsStore.PROVIDER_ELEVENLABS -> ElevenLabsProvider
    else -> FishAudioProvider
}

/** MIME type for a sample file — uploads can be recorded M4A or imported MP3/WAV/etc. */
internal fun audioMimeFor(file: File): String = when (file.extension.lowercase()) {
    "mp3" -> "audio/mpeg"
    "wav" -> "audio/wav"
    "ogg", "opus" -> "audio/ogg"
    "flac" -> "audio/flac"
    else -> "audio/mp4"
}

/** Runs a call, converting low-level network failures into friendly, actionable messages. */
internal fun executeCall(
    request: okhttp3.Request,
    client: OkHttpClient = Http.client,
): okhttp3.Response =
    try {
        client.newCall(request).execute()
    } catch (e: java.net.UnknownHostException) {
        throw IllegalStateException(
            "No internet or DNS blocked. Toggle airplane mode, try Wi-Fi, or set " +
                "Private DNS to dns.google in phone settings, then retry.",
        )
    } catch (e: java.net.SocketTimeoutException) {
        throw IllegalStateException("Network too slow — timed out. Try again on a better connection.")
    } catch (e: javax.net.ssl.SSLException) {
        throw IllegalStateException("Secure connection failed — check network and retry.")
    }

internal fun httpError(code: Int, body: String): String = when (code) {
    401, 403 -> "Invalid API key (HTTP $code)"
    402 -> "Not enough credit on your account (HTTP 402) — top up and retry"
    429 -> "Rate limited (HTTP 429) — wait a moment and retry"
    else -> "Server error (HTTP $code): ${body.take(120)}"
}
