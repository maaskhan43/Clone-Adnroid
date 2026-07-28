package com.clonecast.app.tts

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.File

object ElevenLabsProvider : TtsProvider {
    override val displayName = "ElevenLabs"

    private const val BASE = "https://api.elevenlabs.io"
    private val json = Json { ignoreUnknownKeys = true }

    override suspend fun checkConnection(apiKey: String): Result<String> =
        withContext(Dispatchers.IO) {
            runCatching {
                val request = Request.Builder()
                    .url("$BASE/v1/user")
                    .header("xi-api-key", apiKey)
                    .get()
                    .build()
                executeCall(request).use { response ->
                    if (!response.isSuccessful) {
                        throw IllegalStateException(
                            httpError(response.code, response.body?.string().orEmpty()),
                        )
                    }
                    "Connected ✓"
                }
            }
        }

    override suspend fun cloneVoice(apiKey: String, name: String, sampleFile: File): Result<String> =
        withContext(Dispatchers.IO) {
            runCatching {
                val body = MultipartBody.Builder()
                    .setType(MultipartBody.FORM)
                    .addFormDataPart("name", name)
                    .addFormDataPart(
                        "files",
                        sampleFile.name,
                        sampleFile.asRequestBody(audioMimeFor(sampleFile).toMediaType()),
                    )
                    .build()
                val request = Request.Builder()
                    .url("$BASE/v1/voices/add")
                    .header("xi-api-key", apiKey)
                    .post(body)
                    .build()
                executeCall(request).use { response ->
                    val text = response.body?.string().orEmpty()
                    if (!response.isSuccessful) {
                        throw IllegalStateException(httpError(response.code, text))
                    }
                    json.parseToJsonElement(text).jsonObject["voice_id"]?.jsonPrimitive?.content
                        ?: throw IllegalStateException("No voice ID in response")
                }
            }
        }

    override suspend fun generate(apiKey: String, voiceId: String, text: String): Result<ByteArray> =
        withContext(Dispatchers.IO) {
            runCatching {
                val payload = buildJsonObject {
                    put("text", text)
                    put("model_id", "eleven_multilingual_v2")
                }
                val request = Request.Builder()
                    .url("$BASE/v1/text-to-speech/$voiceId?output_format=mp3_44100_128")
                    .header("xi-api-key", apiKey)
                    .post(payload.toString().toRequestBody("application/json".toMediaType()))
                    .build()
                executeCall(request).use { response ->
                    if (!response.isSuccessful) {
                        val err = response.body?.string().orEmpty()
                        throw IllegalStateException(httpError(response.code, err))
                    }
                    val bytes = response.body?.bytes()
                    if (bytes == null || bytes.isEmpty()) {
                        throw IllegalStateException("Empty audio response")
                    }
                    bytes
                }
            }
        }
}
