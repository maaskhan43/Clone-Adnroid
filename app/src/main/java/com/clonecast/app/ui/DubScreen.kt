package com.clonecast.app.ui

import android.content.Context
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.clonecast.app.audio.AudioExtractor
import com.clonecast.app.data.AudioExport
import com.clonecast.app.data.ProfileStore
import com.clonecast.app.data.SettingsStore
import com.clonecast.app.data.VoiceProfile
import com.clonecast.app.data.Genre
import com.clonecast.app.stt.GroqLlm
import com.clonecast.app.stt.GroqStt
import com.clonecast.app.tts.FishLibrary
import com.clonecast.app.tts.LibraryVoice
import com.clonecast.app.tts.providerFor
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.util.UUID

private enum class DubStage { IDLE, EXTRACTING, TRANSCRIBING, LABELING }
private enum class LineStatus { PENDING, WORKING, DONE, ERROR }

private data class DubLineUi(
    val index: Int,
    val tag: String,
    val text: String,
    val status: LineStatus = LineStatus.PENDING,
    val file: File? = null,
    val error: String? = null,
)

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun DubScreen() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val profiles by ProfileStore.profilesFlow(context).collectAsState(initial = emptyList())
    val cloned = profiles.filter { it.voiceId != null }

    // Auto-assignment uses ready-made library voices (no recorded sample) when available,
    // so the user's own cloned voice is never used for dubbing unless picked manually.
    val dubPool =
        if (cloned.any { it.samplePath == null }) cloned.filter { it.samplePath == null }
        else cloned

    var mediaUri by remember { mutableStateOf<Uri?>(null) }
    var targetLang by remember { mutableStateOf("Hindi") }
    var stage by remember { mutableStateOf(DubStage.IDLE) }
    var script by remember { mutableStateOf("") }
    var genderByTag by remember { mutableStateOf<Map<String, String>>(emptyMap()) }
    var voiceByTag by remember { mutableStateOf<Map<String, String>>(emptyMap()) }
    var lines by remember { mutableStateOf<List<DubLineUi>>(emptyList()) }
    var lastGenScript by remember { mutableStateOf("") }
    var generating by remember { mutableStateOf(false) }
    var exporting by remember { mutableStateOf(false) }
    var exportedUri by remember { mutableStateOf<Uri?>(null) }
    var title by remember { mutableStateOf("") }
    var message by remember { mutableStateOf<String?>(null) }
    var expandedTag by remember { mutableStateOf<String?>(null) }
    var fetchingVoices by remember { mutableStateOf(false) }
    var pendingReassign by remember { mutableStateOf(false) }

    val uniqueTags = remember(script) { parseDubScript(script).map { it.first }.distinct() }
    val jobDir = remember { File(context.filesDir, "output/dub") }

    fun assignVoice(tag: String, genders: Map<String, String>, used: MutableMap<String, Int>): String? {
        val wantFemale = genders[tag] == "female"
        val males = dubPool.filter { it.gender != "female" }
        val females = dubPool.filter { it.gender == "female" }
        val pool = when {
            wantFemale && females.isNotEmpty() -> females
            !wantFemale && males.isNotEmpty() -> males
            dubPool.isNotEmpty() -> dubPool
            else -> return null
        }
        val key = if (wantFemale) "f" else "m"
        val index = used.getOrDefault(key, 0)
        used[key] = index + 1
        return pool[index % pool.size].id
    }

    fun autoAssignAll(genders: Map<String, String>, tags: List<String>) {
        val used = mutableMapOf<String, Int>()
        voiceByTag = tags.mapNotNull { tag ->
            assignVoice(tag, genders, used)?.let { tag to it }
        }.toMap()
    }

    fun fetchDubVoices() {
        scope.launch {
            fetchingVoices = true
            message = null
            val found = mutableListOf<LibraryVoice>()
            FishLibrary.topVoices("male").fold(
                onSuccess = { found += it },
                onFailure = { message = it.message },
            )
            FishLibrary.topVoices("female").fold(
                onSuccess = { found += it },
                onFailure = { message = it.message },
            )
            val existingIds = profiles.mapNotNull { it.voiceId }.toSet()
            found.filter { it.id !in existingIds }.forEach { voice ->
                ProfileStore.upsert(
                    context,
                    VoiceProfile(
                        id = UUID.randomUUID().toString(),
                        name = "📚 " + voice.title.take(22),
                        genre = Genre.CUSTOM.name,
                        gender = voice.gender,
                        voiceId = voice.id,
                    ),
                )
            }
            if (found.isNotEmpty()) pendingReassign = true
            fetchingVoices = false
        }
    }

    LaunchedEffect(cloned.size, pendingReassign) {
        if (pendingReassign && script.isNotBlank() && dubPool.isNotEmpty()) {
            autoAssignAll(genderByTag, uniqueTags)
            pendingReassign = false
        }
    }

    val mediaPicker =
        rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
            if (uri != null) {
                mediaUri = uri
                script = ""
                lines = emptyList()
                exportedUri = null
                message = null
            }
        }

    fun runPipeline() {
        val uri = mediaUri ?: return
        scope.launch {
            try {
                message = null
                val groqKey = SettingsStore.groqKeyFlow(context).first().trim()
                if (groqKey.isBlank()) {
                    message = "Add your free Groq key in Settings first (console.groq.com)"
                    return@launch
                }
                val mime = context.contentResolver.getType(uri).orEmpty()
                val audioFile: File =
                    if (mime.startsWith("audio")) {
                        stage = DubStage.EXTRACTING
                        withContext(Dispatchers.IO) { copyPickedAudio(context, uri) }
                    } else {
                        stage = DubStage.EXTRACTING
                        val out = File(context.cacheDir, "dub_audio.m4a")
                        out.delete()
                        AudioExtractor.extractToM4a(context, uri, out)
                        out
                    }
                if (audioFile.length() > 25L * 1024 * 1024) {
                    throw IllegalStateException(
                        "Audio is over 25 MB (Groq free limit) — use a shorter video " +
                            "(split it in the Reels tab first)",
                    )
                }
                stage = DubStage.TRANSCRIBING
                val transcript = GroqStt.transcribe(groqKey, audioFile).getOrThrow()
                stage = DubStage.LABELING
                val raw = GroqLlm.labelAndTranslate(groqKey, transcript, targetLang).getOrThrow()
                val (parsedScript, genders) = parseLlmOutput(raw)
                if (parsedScript.isBlank()) {
                    throw IllegalStateException("AI could not build a script — tap the button to retry")
                }
                script = parsedScript
                genderByTag = genders
                autoAssignAll(genders, parsedScript.let { s -> parseDubScript(s).map { it.first }.distinct() })
                lines = emptyList()
            } catch (e: Exception) {
                message = e.message ?: "Pipeline failed"
            } finally {
                stage = DubStage.IDLE
            }
        }
    }

    fun startGeneration() {
        scope.launch {
            val key = SettingsStore.apiKeyFlow(context).first().trim()
            val providerId = SettingsStore.providerFlow(context).first()
            if (key.isBlank()) {
                message = "Add your Fish Audio API key in Settings first"
                return@launch
            }
            if (lines.isEmpty() || script != lastGenScript) {
                jobDir.deleteRecursively()
                jobDir.mkdirs()
                lastGenScript = script
                lines = parseDubScript(script).mapIndexed { i, (tag, text) ->
                    DubLineUi(index = i, tag = tag, text = text)
                }
            }
            val provider = providerFor(providerId)
            generating = true
            message = null
            exportedUri = null
            for (line in lines) {
                if (line.status == LineStatus.DONE) continue
                val profile: VoiceProfile? = profiles.find { it.id == voiceByTag[line.tag] }
                val voiceId = profile?.voiceId
                if (voiceId == null) {
                    lines = lines.map {
                        if (it.index == line.index) {
                            it.copy(status = LineStatus.ERROR, error = "No voice for @${line.tag}")
                        } else it
                    }
                    continue
                }
                lines = lines.map {
                    if (it.index == line.index) it.copy(status = LineStatus.WORKING, error = null)
                    else it
                }
                val result = provider.generate(key, voiceId, line.text)
                var failed = false
                result.fold(
                    onSuccess = { bytes ->
                        val file = File(jobDir, "line_%04d.mp3".format(line.index))
                        file.writeBytes(bytes)
                        lines = lines.map {
                            if (it.index == line.index) it.copy(status = LineStatus.DONE, file = file)
                            else it
                        }
                    },
                    onFailure = { e ->
                        lines = lines.map {
                            if (it.index == line.index) {
                                it.copy(status = LineStatus.ERROR, error = e.message)
                            } else it
                        }
                        message = e.message
                        failed = true
                    },
                )
                if (failed) break
            }
            generating = false
        }
    }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item(key = "header") {
            Column {
                Text(
                    "Dub Studio",
                    style = MaterialTheme.typography.headlineSmall,
                    color = MaterialTheme.colorScheme.primary,
                )
                Text(
                    "Video in any language → AI detects speakers, translates, and dubs " +
                        "each character with a different voice.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        item(key = "step1") {
            Column {
                Text("1 · Video & language", style = MaterialTheme.typography.labelLarge)
                Spacer(Modifier.height(6.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    OutlinedButton(
                        onClick = { mediaPicker.launch("*/*") },
                        enabled = stage == DubStage.IDLE && !generating,
                    ) { Text(if (mediaUri == null) "🎬 Pick video / audio" else "🎬 Change file") }
                    Spacer(Modifier.width(10.dp))
                    if (mediaUri != null) Text("Selected ✓", style = MaterialTheme.typography.bodySmall)
                }
                Spacer(Modifier.height(8.dp))
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf("Hindi", "English").forEach { lang ->
                        FilterChip(
                            selected = targetLang == lang,
                            onClick = { targetLang = lang },
                            label = { Text(lang) },
                            enabled = stage == DubStage.IDLE && !generating,
                        )
                    }
                }
                Spacer(Modifier.height(8.dp))
                Button(
                    onClick = { runPipeline() },
                    enabled = mediaUri != null && stage == DubStage.IDLE && !generating,
                ) {
                    Text(
                        when (stage) {
                            DubStage.IDLE -> "▶ Transcribe & build script"
                            DubStage.EXTRACTING -> "Extracting audio…"
                            DubStage.TRANSCRIBING -> "Transcribing (Whisper)…"
                            DubStage.LABELING -> "AI labeling & translating…"
                        },
                    )
                }
            }
        }

        if (script.isNotBlank()) {
            item(key = "step2") {
                Column {
                    Text(
                        "2 · Script (fix any wrong lines/speakers)",
                        style = MaterialTheme.typography.labelLarge,
                    )
                    Spacer(Modifier.height(6.dp))
                    OutlinedTextField(
                        value = script,
                        onValueChange = { script = it },
                        enabled = !generating,
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(200.dp),
                    )
                }
            }

            item(key = "mapheader") {
                Column {
                    Text(
                        "3 · Speakers → voices (${cloned.size} voices available)",
                        style = MaterialTheme.typography.labelLarge,
                    )
                    Spacer(Modifier.height(6.dp))
                    OutlinedButton(
                        onClick = { fetchDubVoices() },
                        enabled = !fetchingVoices && !generating,
                    ) {
                        Text(
                            if (fetchingVoices) "Getting voices…"
                            else "⬇ Get ready-made dub voices (♂ + ♀)",
                        )
                    }
                    Text(
                        "Adds popular voices from the Fish library. Your own cloned voice " +
                            "is not used for dubbing unless you pick it yourself.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            items(uniqueTags, key = { "tag_$it" }) { tag ->
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        "@$tag",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.width(90.dp),
                    )
                    FilterChip(
                        selected = genderByTag[tag] != "female",
                        onClick = {
                            genderByTag = genderByTag + (tag to "male")
                            assignVoice(tag, genderByTag, mutableMapOf())?.let {
                                voiceByTag = voiceByTag + (tag to it)
                            }
                        },
                        label = { Text("♂") },
                        enabled = !generating,
                    )
                    Spacer(Modifier.width(4.dp))
                    FilterChip(
                        selected = genderByTag[tag] == "female",
                        onClick = {
                            genderByTag = genderByTag + (tag to "female")
                            assignVoice(tag, genderByTag, mutableMapOf())?.let {
                                voiceByTag = voiceByTag + (tag to it)
                            }
                        },
                        label = { Text("♀") },
                        enabled = !generating,
                    )
                    Spacer(Modifier.width(8.dp))
                    Box {
                        OutlinedButton(
                            onClick = { expandedTag = if (expandedTag == tag) null else tag },
                            enabled = !generating && cloned.isNotEmpty(),
                        ) {
                            Text(
                                profiles.find { it.id == voiceByTag[tag] }?.name ?: "Pick voice",
                                style = MaterialTheme.typography.bodySmall,
                            )
                        }
                        DropdownMenu(
                            expanded = expandedTag == tag,
                            onDismissRequest = { expandedTag = null },
                        ) {
                            cloned.forEach { profile ->
                                DropdownMenuItem(
                                    text = {
                                        Text(
                                            "${if (profile.gender == "female") "♀" else "♂"} " +
                                                profile.name,
                                        )
                                    },
                                    onClick = {
                                        voiceByTag = voiceByTag + (tag to profile.id)
                                        expandedTag = null
                                    },
                                )
                            }
                        }
                    }
                }
            }

            if (cloned.isEmpty()) {
                item(key = "novoice") {
                    Text(
                        "No voices yet — tap \"Get ready-made dub voices\" above to add " +
                            "popular male & female voices in one tap.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }

            item(key = "step4") {
                Column {
                    Spacer(Modifier.height(4.dp))
                    Text("4 · Generate dub", style = MaterialTheme.typography.labelLarge)
                    Spacer(Modifier.height(6.dp))
                    OutlinedTextField(
                        value = title,
                        onValueChange = { title = it },
                        label = { Text("File name") },
                        singleLine = true,
                        enabled = !generating,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(8.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        val hasWork = lines.isNotEmpty() && lines.any { it.status != LineStatus.DONE }
                        Button(
                            onClick = { startGeneration() },
                            enabled = !generating && cloned.isNotEmpty() && voiceByTag.isNotEmpty(),
                        ) {
                            Text(
                                when {
                                    generating -> "Generating…"
                                    hasWork && script == lastGenScript -> "Resume"
                                    else -> "🎙 Generate dub"
                                },
                            )
                        }
                        val allDone = lines.isNotEmpty() && lines.all { it.status == LineStatus.DONE }
                        if (allDone) {
                            Button(
                                onClick = {
                                    scope.launch {
                                        exporting = true
                                        runCatching {
                                            withContext(Dispatchers.IO) {
                                                AudioExport.exportToMusic(
                                                    context,
                                                    title.ifBlank { "Dub" },
                                                    lines.sortedBy { it.index }
                                                        .mapNotNull { it.file },
                                                )
                                            }
                                        }.fold(
                                            onSuccess = { exportedUri = it },
                                            onFailure = { message = it.message },
                                        )
                                        exporting = false
                                    }
                                },
                                enabled = !exporting,
                            ) { Text(if (exporting) "Exporting…" else "Merge & Export") }
                        }
                    }
                    message?.let { msg ->
                        Spacer(Modifier.height(6.dp))
                        Text(
                            msg,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                    }
                    exportedUri?.let { uri ->
                        Spacer(Modifier.height(6.dp))
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                "Saved to Music/CloneCast ✓",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.secondary,
                            )
                            Spacer(Modifier.width(10.dp))
                            OutlinedButton(onClick = { AudioExport.share(context, uri) }) {
                                Text("Share → CapCut")
                            }
                        }
                    }
                    if (lines.isNotEmpty()) {
                        Spacer(Modifier.height(6.dp))
                        Text(
                            "Lines: ${lines.count { it.status == LineStatus.DONE }} / ${lines.size} done" +
                                if (generating) " — keep the app open" else "",
                            style = MaterialTheme.typography.labelLarge,
                        )
                    }
                }
            }

            items(lines, key = { "line_${it.index}" }) { line ->
                Row(modifier = Modifier.fillMaxWidth()) {
                    Text(
                        when (line.status) {
                            LineStatus.PENDING -> "⏳"
                            LineStatus.WORKING -> "⚙️"
                            LineStatus.DONE -> "✅"
                            LineStatus.ERROR -> "❌"
                        },
                    )
                    Spacer(Modifier.width(8.dp))
                    Column {
                        Text(
                            "@${line.tag}: " + line.text.take(44) +
                                if (line.text.length > 44) "…" else "",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        line.error?.let { err ->
                            Text(
                                err,
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.error,
                            )
                        }
                    }
                }
            }
        } else {
            message?.let { msg ->
                item(key = "earlymsg") {
                    Text(
                        msg,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }
        }
    }
}

/** Parses "@tag: text" lines from the editable script. */
private fun parseDubScript(script: String): List<Pair<String, String>> =
    script.lines().mapNotNull { line ->
        val match = Regex("^@([A-Za-z0-9_]+)\\s*:\\s*(.+)$").find(line.trim())
            ?: return@mapNotNull null
        match.groupValues[1].lowercase() to match.groupValues[2].trim()
    }

/** Converts LLM "@tag|gender|text" output into an editable script + gender map. */
private fun parseLlmOutput(raw: String): Pair<String, Map<String, String>> {
    val sb = StringBuilder()
    val genders = mutableMapOf<String, String>()
    raw.lines().forEach { line ->
        val trimmed = line.trim()
        if (!trimmed.startsWith("@")) return@forEach
        val parts = trimmed.removePrefix("@").split("|", limit = 3)
        if (parts.size == 3) {
            val tag = parts[0].trim().lowercase().replace(Regex("[^a-z0-9_]"), "")
            val text = parts[2].trim()
            if (tag.isNotEmpty() && text.isNotEmpty()) {
                genders.putIfAbsent(tag, if (parts[1].contains("f", true)) "female" else "male")
                sb.appendLine("@$tag: $text")
            }
        }
    }
    return sb.toString().trim() to genders
}

private fun copyPickedAudio(context: Context, uri: Uri): File {
    val mime = context.contentResolver.getType(uri).orEmpty()
    val ext = when {
        mime.contains("mpeg") || mime.contains("mp3") -> "mp3"
        mime.contains("wav") -> "wav"
        mime.contains("ogg") || mime.contains("opus") -> "ogg"
        mime.contains("flac") -> "flac"
        else -> "m4a"
    }
    val file = File(context.cacheDir, "dub_audio.$ext")
    context.contentResolver.openInputStream(uri).use { input ->
        if (input == null) throw IllegalStateException("Could not read the selected file")
        file.outputStream().use { input.copyTo(it) }
    }
    return file
}
