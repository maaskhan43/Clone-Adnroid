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

object FishAudioProvider : TtsProvider {
    override val displayName = "Fish Audio"

    private const val BASE = "https://api.fish.audio"

    // Required header on /v1/tts. Allowed: s1, s2-pro, s2.1-pro, s2.1-pro-free.
    // s2.1-pro-free is the free developer tier — switch to s2.1-pro for top quality.
    private const val MODEL = "s2.1-pro-free"

    private val json = Json { ignoreUnknownKeys = true }

    override suspend fun checkConnection(apiKey: String): Result<String> =
        withContext(Dispatchers.IO) {
            runCatching {
                val request = Request.Builder()
                    .url("$BASE/wallet/self/api-credit")
                    .header("Authorization", "Bearer $apiKey")
                    .get()
                    .build()
                executeCall(request).use { response ->
                    val body = response.body?.string().orEmpty()
                    if (!response.isSuccessful) {
                        throw IllegalStateException(httpError(response.code, body))
                    }
                    val credit = runCatching {
                        json.parseToJsonElement(body)
                            .jsonObject["credit"]?.jsonPrimitive?.content
                    }.getOrNull()
                    if (credit != null) "Connected ✓  Credit: $$credit" else "Connected ✓"
                }
            }
        }

    override suspend fun cloneVoice(apiKey: String, name: String, sampleFile: File): Result<String> =
        withContext(Dispatchers.IO) {
            runCatching {
                val body = MultipartBody.Builder()
                    .setType(MultipartBody.FORM)
                    .addFormDataPart("title", name)
                    .addFormDataPart("type", "tts")
                    .addFormDataPart("train_mode", "fast")
                    .addFormDataPart("visibility", "private")
                    .addFormDataPart(
                        "voices",
                        sampleFile.name,
                        sampleFile.asRequestBody(audioMimeFor(sampleFile).toMediaType()),
                    )
                    .build()
                val request = Request.Builder()
                    .url("$BASE/model")
                    .header("Authorization", "Bearer $apiKey")
                    .post(body)
                    .build()
                executeCall(request).use { response ->
                    val text = response.body?.string().orEmpty()
                    if (!response.isSuccessful) {
                        throw IllegalStateException(httpError(response.code, text))
                    }
                    json.parseToJsonElement(text).jsonObject["_id"]?.jsonPrimitive?.content
                        ?: throw IllegalStateException("No voice ID in response")
                }
            }
        }

    override suspend fun generate(apiKey: String, voiceId: String, text: String): Result<ByteArray> =
        withContext(Dispatchers.IO) {
            runCatching {
                val payload = buildJsonObject {
                    put("text", text)
                    put("reference_id", voiceId)
                    put("format", "mp3")
                    put("mp3_bitrate", 128)
                }
                val request = Request.Builder()
                    .url("$BASE/v1/tts")
                    .header("Authorization", "Bearer $apiKey")
                    .header("model", MODEL)
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
