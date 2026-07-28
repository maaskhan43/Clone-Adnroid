package com.clonecast.app.ui

import android.content.Context
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.clonecast.app.audio.SamplePlayer
import com.clonecast.app.data.AudioExport
import com.clonecast.app.stt.GroqStt
import com.clonecast.app.data.ProfileStore
import com.clonecast.app.data.SettingsStore
import com.clonecast.app.data.VoiceProfile
import com.clonecast.app.tts.providerFor
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.util.Locale

private enum class ChunkStatus { PENDING, WORKING, DONE, ERROR }

private data class ChunkUi(
    val index: Int,
    val text: String,
    val status: ChunkStatus = ChunkStatus.PENDING,
    val file: File? = null,
    val error: String? = null,
)

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun GenerateScreen() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val profiles by ProfileStore.profilesFlow(context).collectAsState(initial = emptyList())
    val cloned = profiles.filter { it.voiceId != null }

    var selectedId by remember { mutableStateOf<String?>(null) }
    var title by remember { mutableStateOf("") }
    var script by remember { mutableStateOf("") }
    var lastScript by remember { mutableStateOf("") }
    var chunks by remember { mutableStateOf<List<ChunkUi>>(emptyList()) }
    var running by remember { mutableStateOf(false) }
    var globalError by remember { mutableStateOf<String?>(null) }
    var exportedUri by remember { mutableStateOf<Uri?>(null) }
    var exporting by remember { mutableStateOf(false) }
    var playingIndex by remember { mutableStateOf<Int?>(null) }
    var transcribing by remember { mutableStateOf(false) }
    var sttMessage by remember { mutableStateOf<String?>(null) }

    val player = remember { SamplePlayer() }
    val jobDir = remember { File(context.filesDir, "output/current") }

    LaunchedEffect(cloned) {
        if (selectedId == null || cloned.none { it.id == selectedId }) {
            selectedId = cloned.firstOrNull()?.id
        }
    }

    val audioPicker =
        rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
            if (uri != null) {
                scope.launch {
                    transcribing = true
                    sttMessage = null
                    val result = runCatching {
                        val groqKey = SettingsStore.groqKeyFlow(context).first().trim()
                        if (groqKey.isBlank()) {
                            throw IllegalStateException(
                                "Add your free Groq key in Settings first (console.groq.com)",
                            )
                        }
                        val file = withContext(Dispatchers.IO) { copyUriToCache(context, uri) }
                        try {
                            GroqStt.transcribe(groqKey, file).getOrThrow()
                        } finally {
                            file.delete()
                        }
                    }
                    result.fold(
                        onSuccess = { transcript ->
                            script =
                                if (script.isBlank()) transcript
                                else script + "\n\n" + transcript
                            sttMessage = "Transcribed ✓ — review the script below"
                        },
                        onFailure = { sttMessage = it.message ?: "Transcription failed" },
                    )
                    transcribing = false
                }
            }
        }
    DisposableEffect(Unit) {
        onDispose { player.stop() }
    }

    suspend fun runQueue(profile: VoiceProfile) {
        val key = SettingsStore.apiKeyFlow(context).first().trim()
        val providerId = SettingsStore.providerFlow(context).first()
        if (key.isBlank()) {
            globalError = "Add your API key in Settings first"
            return
        }
        val voiceId = profile.voiceId ?: return
        val provider = providerFor(providerId)
        running = true
        globalError = null
        for (chunk in chunks) {
            if (chunk.status == ChunkStatus.DONE) continue
            chunks = chunks.map {
                if (it.index == chunk.index) it.copy(status = ChunkStatus.WORKING, error = null)
                else it
            }
            val result = provider.generate(key, voiceId, chunk.text)
            var failed = false
            result.fold(
                onSuccess = { bytes ->
                    val file = File(jobDir, "chunk_%03d.mp3".format(chunk.index))
                    file.writeBytes(bytes)
                    chunks = chunks.map {
                        if (it.index == chunk.index) it.copy(status = ChunkStatus.DONE, file = file)
                        else it
                    }
                },
                onFailure = { e ->
                    chunks = chunks.map {
                        if (it.index == chunk.index) {
                            it.copy(status = ChunkStatus.ERROR, error = e.message)
                        } else it
                    }
                    globalError = e.message
                    failed = true
                },
            )
            if (failed) break
        }
        running = false
    }

    fun startOrResume() {
        val profile = cloned.find { it.id == selectedId } ?: return
        exportedUri = null
        if (chunks.isEmpty() || script != lastScript) {
            jobDir.deleteRecursively()
            jobDir.mkdirs()
            lastScript = script
            chunks = splitScript(script).mapIndexed { i, t -> ChunkUi(index = i, text = t) }
        }
        scope.launch { runQueue(profile) }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
    ) {
        Text(
            "Generate Narration",
            style = MaterialTheme.typography.headlineSmall,
            color = MaterialTheme.colorScheme.primary,
        )
        Spacer(Modifier.height(12.dp))

        if (cloned.isEmpty()) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text("🎙️", fontSize = 48.sp)
                Spacer(Modifier.height(12.dp))
                Text(
                    "No cloned voices yet.\nGo to Profiles → record a sample → Clone voice.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                )
            }
            return@Column
        }

        Text("Voice", style = MaterialTheme.typography.labelLarge)
        Spacer(Modifier.height(6.dp))
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            cloned.forEach { profile ->
                FilterChip(
                    selected = selectedId == profile.id,
                    onClick = { selectedId = profile.id },
                    label = { Text("${profile.genreEnum.emoji} ${profile.name}") },
                    enabled = !running,
                )
            }
        }

        Spacer(Modifier.height(12.dp))
        OutlinedTextField(
            value = title,
            onValueChange = { title = it },
            label = { Text("Video title (for the MP3 file name)") },
            singleLine = true,
            enabled = !running,
            modifier = Modifier.fillMaxWidth(),
        )

        Spacer(Modifier.height(12.dp))
        OutlinedTextField(
            value = script,
            onValueChange = { script = it },
            label = { Text("Paste your recap script here") },
            enabled = !running,
            modifier = Modifier
                .fillMaxWidth()
                .height(140.dp),
        )
        val chars = script.length
        val estUsd = chars / 1_000_000.0 * 15
        Text(
            "$chars characters ≈ \$${"%.2f".format(Locale.US, estUsd)} (Fish Audio, approx.)",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 4.dp),
        )

        Spacer(Modifier.height(8.dp))
        val clipboard = LocalClipboardManager.current
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(
                onClick = { audioPicker.launch("audio/*") },
                enabled = !running && !transcribing,
            ) {
                Text(if (transcribing) "Transcribing…" else "🎤 Script from audio (free)")
            }
            if (script.isNotBlank()) {
                OutlinedButton(
                    onClick = {
                        clipboard.setText(AnnotatedString(script))
                        sttMessage = "Copied to clipboard ✓ — paste it anywhere"
                    },
                ) { Text("📋 Copy") }
            }
        }
        Text(
            "Speak your recap into any voice-memo app, pick the file here — " +
                "it becomes script text.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 2.dp),
        )
        sttMessage?.let { message ->
            Text(
                message,
                style = MaterialTheme.typography.bodySmall,
                color =
                    if (message.contains("✓")) MaterialTheme.colorScheme.secondary
                    else MaterialTheme.colorScheme.error,
                modifier = Modifier.padding(top = 4.dp),
            )
        }

        Spacer(Modifier.height(12.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            val hasWork = chunks.isNotEmpty() && chunks.any { it.status != ChunkStatus.DONE }
            Button(
                onClick = { startOrResume() },
                enabled = !running && script.isNotBlank() && selectedId != null,
            ) {
                Text(
                    when {
                        running -> "Generating…"
                        hasWork && script == lastScript -> "Resume"
                        else -> "Generate"
                    },
                )
            }
            if (chunks.isNotEmpty() && !running) {
                OutlinedButton(
                    onClick = {
                        player.stop()
                        playingIndex = null
                        chunks = emptyList()
                        exportedUri = null
                        globalError = null
                    },
                ) { Text("Clear") }
            }
            val allDone = chunks.isNotEmpty() && chunks.all { it.status == ChunkStatus.DONE }
            if (allDone) {
                Button(
                    onClick = {
                        scope.launch {
                            exporting = true
                            globalError = null
                            runCatching {
                                withContext(Dispatchers.IO) {
                                    AudioExport.exportToMusic(
                                        context,
                                        title.ifBlank { "CloneCast narration" },
                                        chunks.mapNotNull { it.file },
                                    )
                                }
                            }.fold(
                                onSuccess = { exportedUri = it },
                                onFailure = { globalError = it.message },
                            )
                            exporting = false
                        }
                    },
                    enabled = !exporting,
                ) { Text(if (exporting) "Exporting…" else "Merge & Export") }
            }
        }

        globalError?.let { message ->
            Spacer(Modifier.height(8.dp))
            Text(
                message,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        }
        exportedUri?.let { uri ->
            Spacer(Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    "Saved to Music/CloneCast ✓",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.secondary,
                )
                Spacer(Modifier.width(12.dp))
                OutlinedButton(onClick = { AudioExport.share(context, uri) }) {
                    Text("Share → CapCut")
                }
            }
        }

        if (chunks.isNotEmpty()) {
            Spacer(Modifier.height(12.dp))
            val done = chunks.count { it.status == ChunkStatus.DONE }
            Text(
                "Chunks: $done / ${chunks.size} done" +
                    if (running) " — keep the app open" else "",
                style = MaterialTheme.typography.labelLarge,
            )
            Spacer(Modifier.height(6.dp))
            LazyColumn(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                items(chunks, key = { it.index }) { chunk ->
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            when (chunk.status) {
                                ChunkStatus.PENDING -> "⏳"
                                ChunkStatus.WORKING -> "⚙️"
                                ChunkStatus.DONE -> "✅"
                                ChunkStatus.ERROR -> "❌"
                            },
                        )
                        Spacer(Modifier.width(8.dp))
                        Column(Modifier.weight(1f)) {
                            Text(
                                "${chunk.index + 1}. " + chunk.text.take(48) +
                                    if (chunk.text.length > 48) "…" else "",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            chunk.error?.let { err ->
                                Text(
                                    err,
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.error,
                                )
                            }
                        }
                        if (chunk.status == ChunkStatus.DONE && chunk.file != null) {
                            IconButton(
                                onClick = {
                                    if (playingIndex == chunk.index) {
                                        player.stop()
                                        playingIndex = null
                                    } else {
                                        playingIndex = chunk.index
                                        player.play(chunk.file.absolutePath) {
                                            playingIndex = null
                                        }
                                    }
                                },
                            ) {
                                Icon(
                                    Icons.Filled.PlayArrow,
                                    contentDescription = "Play chunk",
                                    tint =
                                        if (playingIndex == chunk.index) {
                                            MaterialTheme.colorScheme.primary
                                        } else MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                        if (chunk.status == ChunkStatus.ERROR && !running) {
                            IconButton(onClick = { startOrResume() }) {
                                Icon(
                                    Icons.Filled.Refresh,
                                    contentDescription = "Retry",
                                    tint = MaterialTheme.colorScheme.primary,
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

/** Copies a picked audio Uri into cache with a sensible extension for the STT upload. */
private fun copyUriToCache(context: Context, uri: Uri): File {
    val mime = context.contentResolver.getType(uri).orEmpty()
    val ext = when {
        mime.contains("mpeg") || mime.contains("mp3") -> "mp3"
        mime.contains("wav") -> "wav"
        mime.contains("ogg") || mime.contains("opus") -> "ogg"
        mime.contains("flac") -> "flac"
        else -> "m4a"
    }
    val file = File(context.cacheDir, "stt_input.$ext")
    context.contentResolver.openInputStream(uri).use { input ->
        if (input == null) throw IllegalStateException("Could not read the selected file")
        file.outputStream().use { input.copyTo(it) }
    }
    return file
}

/** Splits a script into ~[maxLen]-char chunks at sentence boundaries. */
private fun splitScript(script: String, maxLen: Int = 1500): List<String> {
    val sentences = Regex("(?<=[.!?…])\\s+").split(script.trim()).filter { it.isNotBlank() }
    val out = mutableListOf<String>()
    val sb = StringBuilder()
    for (sentence in sentences) {
        if (sb.isNotEmpty() && sb.length + sentence.length + 1 > maxLen) {
            out += sb.toString()
            sb.clear()
        }
        if (sentence.length > maxLen) {
            if (sb.isNotEmpty()) {
                out += sb.toString()
                sb.clear()
            }
            sentence.chunked(maxLen).forEach { out += it }
        } else {
            if (sb.isNotEmpty()) sb.append(' ')
            sb.append(sentence)
        }
    }
    if (sb.isNotEmpty()) out += sb.toString()
    return out
}
