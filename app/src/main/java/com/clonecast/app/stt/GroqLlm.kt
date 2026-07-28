package com.clonecast.app.stt

import com.clonecast.app.tts.executeCall
import com.clonecast.app.tts.httpError
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.addJsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

/** Free LLM (Llama on Groq, same key as Whisper) for speaker labeling + translation. */
object GroqLlm {
    private const val URL = "https://api.groq.com/openai/v1/chat/completions"
    private const val MODEL = "llama-3.3-70b-versatile"
    private val json = Json { ignoreUnknownKeys = true }

    private const val SYSTEM_PROMPT =
        "You convert raw video transcripts into dubbing scripts.\n" +
            "Rules:\n" +
            "1. Split the transcript into individual spoken lines.\n" +
            "2. Infer the distinct speakers from context. Label each line with a consistent " +
            "tag: @char1, @char2, ... The same person must always keep the same tag. " +
            "Use at most 8 tags; minor/background characters share tags.\n" +
            "3. Guess each speaker's gender (male or female).\n" +
            "4. Translate every line into natural, everyday spoken form of the TARGET " +
            "LANGUAGE the user gives.\n" +
            "Output format — one output line per spoken line, EXACTLY:\n" +
            "@tag|male or female|translated line\n" +
            "Nothing else: no headings, no explanations, no numbering, no blank lines."

    suspend fun labelAndTranslate(
        apiKey: String,
        transcript: String,
        targetLanguage: String,
    ): Result<String> = withContext(Dispatchers.IO) {
        runCatching {
            val payload = buildJsonObject {
                put("model", MODEL)
                put("temperature", 0.3)
                put("max_tokens", 8192)
                putJsonArray("messages") {
                    addJsonObject {
                        put("role", "system")
                        put("content", SYSTEM_PROMPT)
                    }
                    addJsonObject {
                        put("role", "user")
                        put(
                            "content",
                            "TARGET LANGUAGE: $targetLanguage\n\nTRANSCRIPT:\n$transcript",
                        )
                    }
                }
            }
            val request = Request.Builder()
                .url(URL)
                .header("Authorization", "Bearer $apiKey")
                .post(payload.toString().toRequestBody("application/json".toMediaType()))
                .build()
            executeCall(request).use { response ->
                val body = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    throw IllegalStateException(httpError(response.code, body))
                }
                runCatching {
                    json.parseToJsonElement(body)
                        .jsonObject["choices"]!!.jsonArray[0]
                        .jsonObject["message"]!!.jsonObject["content"]!!
                        .jsonPrimitive.content
                }.getOrElse { throw IllegalStateException("Unexpected AI response format") }
            }
        }
    }
}
