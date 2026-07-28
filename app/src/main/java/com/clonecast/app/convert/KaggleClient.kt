package com.clonecast.app.convert

import com.clonecast.app.tts.Http
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import okhttp3.Credentials
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okio.BufferedSink
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * Raw Kaggle API v1 client. Endpoints, JSON field names, and enum casings are
 * source-verified against Kaggle/kagglesdk (see PLAN-VOICE-CONVERT.md section 5).
 * Auth: HTTP Basic. All JSON keys camelCase; enums are UPPERCASE names.
 *
 * Guardrail: only exact clonecast-* slugs are ever addressed; this client has
 * no list/enumerate calls for kernels or datasets.
 */
object KaggleClient {
    private const val BASE = "https://www.kaggle.com/api/v1"
    private val json = Json { ignoreUnknownKeys = true }
    private val jsonMedia = "application/json".toMediaType()

    /** Uploads/downloads of 20-40 MB audio need longer timeouts than the shared client. */
    private val transferClient: OkHttpClient = Http.client.newBuilder()
        .readTimeout(10, TimeUnit.MINUTES)
        .writeTimeout(10, TimeUnit.MINUTES)
        .build()

    data class Creds(val username: String, val apiKey: String) {
        val header: String get() = Credentials.basic(username, apiKey)
    }

    data class GpuQuota(val usedSeconds: Long, val totalSeconds: Long)

    data class KernelState(val status: String, val failureMessage: String?)

    data class OutputFile(val fileName: String, val url: String)

    private fun authed(creds: Creds, url: String): Request.Builder =
        Request.Builder().url(url).header("Authorization", creds.header)

    private fun parse(body: String): JsonObject =
        runCatching { json.parseToJsonElement(body).jsonObject }
            .getOrElse { throw IllegalStateException("Unexpected Kaggle response: ${body.take(120)}") }

    private fun execute(request: Request, client: OkHttpClient = Http.client): String {
        com.clonecast.app.tts.executeCall(request, client).use { response ->
            val body = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                throw IllegalStateException(kaggleError(response.code, body))
            }
            return body
        }
    }

    private fun kaggleError(code: Int, body: String): String = when (code) {
        401, 403 -> "Kaggle rejected the credentials (HTTP $code) — check username & API key"
        404 -> "NOT_FOUND"
        429 -> "Kaggle rate limit (HTTP 429) — wait a minute and retry"
        else -> "Kaggle error (HTTP $code): ${body.take(160)}"
    }

    fun isNotFound(e: Throwable): Boolean = e.message == "NOT_FOUND"

    /** Proto Duration JSON can be "123.4s", a bare number, or {"seconds": n}. */
    private fun parseDurationSeconds(element: kotlinx.serialization.json.JsonElement?): Long {
        if (element == null) return 0
        runCatching {
            val obj = element.jsonObject
            return obj["seconds"]?.jsonPrimitive?.content?.toDouble()?.toLong() ?: 0
        }
        val raw = runCatching { element.jsonPrimitive.content }.getOrDefault("")
        return raw.removeSuffix("s").toDoubleOrNull()?.toLong() ?: 0
    }

    // --- 5.1 Test connection + quota ---

    suspend fun gpuQuota(creds: Creds): Result<GpuQuota> = withContext(Dispatchers.IO) {
        runCatching {
            val body = execute(authed(creds, "$BASE/kernels/quota").get().build())
            val gpu = parse(body)["gpuQuota"]?.jsonObject
            GpuQuota(
                usedSeconds = parseDurationSeconds(gpu?.get("timeUsed")),
                totalSeconds = parseDurationSeconds(gpu?.get("totalTimeAllowed")),
            )
        }
    }

    // --- 5.2 Blob upload (3-step) ---

    suspend fun uploadBlob(
        creds: Creds,
        file: File,
        contentType: String,
        onProgress: (Float) -> Unit = {},
    ): Result<String> = withContext(Dispatchers.IO) {
        runCatching {
            val start = buildJsonObject {
                put("type", "DATASET")
                put("name", file.name)
                put("contentType", contentType)
                put("contentLength", file.length())
                put("lastModifiedEpochSeconds", file.lastModified() / 1000)
            }
            val startBody = execute(
                authed(creds, "$BASE/blobs/upload")
                    .post(start.toString().toRequestBody(jsonMedia))
                    .build(),
            )
            val startJson = parse(startBody)
            val token = startJson["token"]?.jsonPrimitive?.content
                ?: throw IllegalStateException("No upload token from Kaggle")
            val createUrl = startJson["createUrl"]?.jsonPrimitive?.content
                ?: throw IllegalStateException("No upload URL from Kaggle")

            val put = Request.Builder()
                .url(createUrl)
                .put(progressBody(file, contentType, onProgress))
                .build()
            com.clonecast.app.tts.executeCall(put, transferClient).use { response ->
                if (!response.isSuccessful) {
                    throw IllegalStateException(
                        "Upload to storage failed (HTTP ${response.code}) — check connection and retry",
                    )
                }
            }
            token
        }
    }

    private fun progressBody(
        file: File,
        contentType: String,
        onProgress: (Float) -> Unit,
    ): RequestBody = object : RequestBody() {
        override fun contentType() = contentType.toMediaType()
        override fun contentLength() = file.length()
        override fun writeTo(sink: BufferedSink) {
            val total = file.length().coerceAtLeast(1)
            var written = 0L
            file.inputStream().use { input ->
                val buffer = ByteArray(1 shl 16)
                while (true) {
                    val read = input.read(buffer)
                    if (read < 0) break
                    sink.write(buffer, 0, read)
                    written += read
                    onProgress(written.toFloat() / total)
                }
            }
        }
    }

    // --- 5.3 / 5.4 Dataset create + version ---

    suspend fun createDataset(
        creds: Creds,
        slug: String,
        title: String,
        tokens: List<String>,
    ): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            val payload = buildJsonObject {
                put("title", title)
                put("slug", slug)
                put("ownerSlug", creds.username)
                put("licenseName", "other")
                put("isPrivate", true)
                put("files", buildJsonArray {
                    tokens.forEach { add(buildJsonObject { put("token", it) }) }
                })
            }
            val body = execute(
                authed(creds, "$BASE/datasets/create/new")
                    .post(payload.toString().toRequestBody(jsonMedia))
                    .build(),
            )
            parse(body)["error"]?.jsonPrimitive?.content
                ?.takeIf { it.isNotBlank() && it != "null" }
                ?.let { throw IllegalStateException("Dataset create failed: $it") }
            Unit
        }
    }

    suspend fun versionDataset(
        creds: Creds,
        slug: String,
        notes: String,
        tokens: List<String>,
    ): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            val payload = buildJsonObject {
                put("versionNotes", notes)
                put("deleteOldVersions", true)
                put("files", buildJsonArray {
                    tokens.forEach { add(buildJsonObject { put("token", it) }) }
                })
            }
            val body = execute(
                authed(creds, "$BASE/datasets/create/version/${creds.username}/$slug")
                    .post(payload.toString().toRequestBody(jsonMedia))
                    .build(),
            )
            parse(body)["error"]?.jsonPrimitive?.content
                ?.takeIf { it.isNotBlank() && it != "null" }
                ?.let { throw IllegalStateException("Dataset version failed: $it") }
            Unit
        }
    }

    // --- 5.5 Dataset status ---

    suspend fun datasetStatus(creds: Creds, slug: String): Result<String> =
        withContext(Dispatchers.IO) {
            runCatching {
                val body = execute(
                    authed(creds, "$BASE/datasets/status/${creds.username}/$slug").get().build(),
                )
                // Response is {"status": "READY"} (enum name) — parse defensively.
                runCatching { parse(body)["status"]?.jsonPrimitive?.content }
                    .getOrNull()
                    ?.uppercase()
                    ?: body.trim().trim('"').uppercase()
            }
        }

    // --- 5.6 Push converter kernel ---

    suspend fun pushKernel(
        creds: Creds,
        kernelSlug: String,
        scriptText: String,
        datasetSources: List<String>,
    ): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            val payload = buildJsonObject {
                put("slug", "${creds.username}/$kernelSlug")
                put("newTitle", kernelSlug)
                put("text", scriptText)
                put("language", "python")
                put("kernelType", "script")
                put("isPrivate", true)
                put("enableInternet", true)
                put("machineShape", "NvidiaTeslaT4")
                put("datasetDataSources", buildJsonArray {
                    datasetSources.forEach { add(kotlinx.serialization.json.JsonPrimitive(it)) }
                })
            }
            val body = execute(
                authed(creds, "$BASE/kernels/push")
                    .post(payload.toString().toRequestBody(jsonMedia))
                    .build(),
            )
            parse(body)["error"]?.jsonPrimitive?.content
                ?.takeIf { it.isNotBlank() && it != "null" }
                ?.let { throw IllegalStateException("Kernel push failed: $it") }
            Unit
        }
    }

    // --- 5.7 Kernel status ---

    suspend fun kernelStatus(creds: Creds, kernelSlug: String): Result<KernelState> =
        withContext(Dispatchers.IO) {
            runCatching {
                val url = "$BASE/kernels/status".toHttpUrl().newBuilder()
                    .addQueryParameter("userName", creds.username)
                    .addQueryParameter("kernelSlug", kernelSlug)
                    .build()
                val body = execute(authed(creds, url.toString()).get().build())
                val obj = parse(body)
                KernelState(
                    status = obj["status"]?.jsonPrimitive?.content?.uppercase() ?: "UNKNOWN",
                    failureMessage = obj["failureMessage"]?.jsonPrimitive?.content,
                )
            }
        }

    // --- 5.8 Kernel output ---

    suspend fun kernelOutput(creds: Creds, kernelSlug: String): Result<List<OutputFile>> =
        withContext(Dispatchers.IO) {
            runCatching {
                val url = "$BASE/kernels/output".toHttpUrl().newBuilder()
                    .addQueryParameter("userName", creds.username)
                    .addQueryParameter("kernelSlug", kernelSlug)
                    .build()
                val body = execute(authed(creds, url.toString()).get().build())
                parse(body)["files"]?.jsonArray.orEmpty().mapNotNull { element ->
                    val obj = element.jsonObject
                    val name = obj["fileName"]?.jsonPrimitive?.content ?: return@mapNotNull null
                    val fileUrl = obj["url"]?.jsonPrimitive?.content ?: return@mapNotNull null
                    OutputFile(name, fileUrl)
                }
            }
        }

    /** Downloads a signed output URL to [dest]. Auth header only for kaggle.com URLs. */
    suspend fun downloadFile(
        creds: Creds,
        url: String,
        dest: File,
        onProgress: (Float) -> Unit = {},
    ): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            val builder = Request.Builder().url(url)
            if (url.toHttpUrl().host.endsWith("kaggle.com")) {
                builder.header("Authorization", creds.header)
            }
            com.clonecast.app.tts.executeCall(builder.get().build(), transferClient).use { response ->
                if (!response.isSuccessful) {
                    throw IllegalStateException("Download failed (HTTP ${response.code})")
                }
                val bodyStream = response.body?.byteStream()
                    ?: throw IllegalStateException("Empty download")
                val total = (response.body?.contentLength() ?: -1L).coerceAtLeast(1)
                dest.outputStream().use { out ->
                    val buffer = ByteArray(1 shl 16)
                    var written = 0L
                    while (true) {
                        val read = bodyStream.read(buffer)
                        if (read < 0) break
                        out.write(buffer, 0, read)
                        written += read
                        onProgress(written.toFloat() / total)
                    }
                }
            }
        }
    }
}
