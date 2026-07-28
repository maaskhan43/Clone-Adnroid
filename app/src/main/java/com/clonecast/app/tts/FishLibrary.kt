package com.clonecast.app.tts

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.Request

data class LibraryVoice(
    val id: String,
    val title: String,
    val gender: String,
    val likes: Int,
)

/** Fish Audio's public voice library — browsable without any API key. */
object FishLibrary {
    private val json = Json { ignoreUnknownKeys = true }

    suspend fun topVoices(
        gender: String,
        language: String = "en",
        count: Int = 3,
    ): Result<List<LibraryVoice>> = withContext(Dispatchers.IO) {
        runCatching {
            val url =
                "https://api.fish.audio/model?page_size=$count&tag=$gender&language=$language"
            val request = Request.Builder().url(url).get().build()
            executeCall(request).use { response ->
                val body = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    throw IllegalStateException(httpError(response.code, body))
                }
                json.parseToJsonElement(body).jsonObject["items"]!!.jsonArray.mapNotNull { el ->
                    val obj = el.jsonObject
                    val id = obj["_id"]?.jsonPrimitive?.content ?: return@mapNotNull null
                    val title = obj["title"]?.jsonPrimitive?.content ?: "Voice"
                    val likes = obj["like_count"]?.jsonPrimitive?.content?.toIntOrNull() ?: 0
                    LibraryVoice(id = id, title = title, gender = gender, likes = likes)
                }
            }
        }
    }
}
