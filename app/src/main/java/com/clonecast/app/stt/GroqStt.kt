package com.clonecast.app.stt

import com.clonecast.app.tts.audioMimeFor
import com.clonecast.app.tts.executeCall
import com.clonecast.app.tts.httpError
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import java.io.File

/** Free speech-to-text via Groq's Whisper API (free tier, no card needed). */
object GroqStt {
    private const val URL = "https://api.groq.com/openai/v1/audio/transcriptions"

    // whisper-large-v3 = highest accuracy; free tier covers it (25 MB max file).
    private const val MODEL = "whisper-large-v3"

    suspend fun transcribe(apiKey: String, audio: File): Result<String> =
        withContext(Dispatchers.IO) {
            runCatching {
                if (audio.length() > 25L * 1024 * 1024) {
                    throw IllegalStateException(
                        "File is over 25 MB (Groq free limit) — split the audio and try again",
                    )
                }
                val body = MultipartBody.Builder()
                    .setType(MultipartBody.FORM)
                    .addFormDataPart("model", MODEL)
                    .addFormDataPart("response_format", "text")
                    .addFormDataPart(
                        "file",
                        audio.name,
                        audio.asRequestBody(audioMimeFor(audio).toMediaType()),
                    )
                    .build()
                val request = Request.Builder()
                    .url(URL)
                    .header("Authorization", "Bearer $apiKey")
                    .post(body)
                    .build()
                executeCall(request).use { response ->
                    val text = response.body?.string().orEmpty()
                    if (!response.isSuccessful) {
                        throw IllegalStateException(httpError(response.code, text))
                    }
                    text.trim().ifEmpty {
                        throw IllegalStateException("Empty transcript — is the audio silent?")
                    }
                }
            }
        }
}
