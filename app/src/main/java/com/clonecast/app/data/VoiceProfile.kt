package com.clonecast.app.data

import kotlinx.serialization.Serializable

enum class Genre(val emoji: String, val label: String, val recordingTip: String) {
    COMEDY(
        "🎭", "Comedy",
        "Sound energetic and playful — smile while you talk, vary your pitch.",
    ),
    HORROR(
        "👻", "Horror",
        "Speak low and slow, almost a whisper, with pauses… build tension.",
    ),
    DRAMA(
        "💔", "Drama",
        "Warm, emotional, heartfelt — like telling a sad story to a friend.",
    ),
    ROMANCE(
        "❤️", "Romance",
        "Soft and tender, gentle pace, intimate tone.",
    ),
    ACTION(
        "💥", "Action",
        "Fast, punchy, intense — like commentating a chase scene.",
    ),
    CUSTOM(
        "⚙️", "Custom",
        "Speak naturally in the exact style you want this voice to have.",
    ),
}

@Serializable
data class VoiceProfile(
    val id: String,
    val name: String,
    val genre: String = Genre.CUSTOM.name,
    val samplePath: String? = null,
    val voiceId: String? = null,
    val gender: String = "male",
) {
    val genreEnum: Genre
        get() = runCatching { Genre.valueOf(genre) }.getOrDefault(Genre.CUSTOM)
}
