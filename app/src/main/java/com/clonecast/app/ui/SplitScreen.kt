package com.clonecast.app.ui

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
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.clonecast.app.data.VideoExport
import com.clonecast.app.video.VideoSplitter
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

private enum class PartStatus { PENDING, WORKING, DONE, ERROR }

private data class PartUi(
    val index: Int,
    val startMs: Long,
    val endMs: Long,
    val status: PartStatus = PartStatus.PENDING,
    val error: String? = null,
)

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun SplitScreen() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    var videoUri by remember { mutableStateOf<Uri?>(null) }
    var durationMs by remember { mutableStateOf(0L) }
    var partSeconds by remember { mutableStateOf(30) }
    var customMode by remember { mutableStateOf(false) }
    var customText by remember { mutableStateOf("") }
    var reel by remember { mutableStateOf(true) }
    var title by remember { mutableStateOf("") }
    var parts by remember { mutableStateOf<List<PartUi>>(emptyList()) }
    var running by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf<String?>(null) }
    var splitJob by remember { mutableStateOf<Job?>(null) }

    val videoPicker =
        rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
            if (uri != null) {
                videoUri = uri
                parts = emptyList()
                message = null
                scope.launch {
                    durationMs = withContext(Dispatchers.IO) {
                        VideoSplitter.durationMs(context, uri)
                    }
                    if (durationMs <= 0L) {
                        message = "Could not read this video — try another file"
                        videoUri = null
                    }
                }
            }
        }

    val effectiveSeconds =
        if (customMode) customText.toIntOrNull() ?: 0 else partSeconds
    val partLenValid = effectiveSeconds in 5..3600

    fun buildParts(): List<PartUi> {
        val partMs = effectiveSeconds * 1000L
        val total = ((durationMs + partMs - 1) / partMs).toInt()
        return (0 until total).map { i ->
            val overlap = if (i > 0) VideoSplitter.RECAP_OVERLAP_MS else 0L
            PartUi(
                index = i,
                startMs = maxOf(0L, i * partMs - overlap),
                endMs = minOf(durationMs, (i + 1) * partMs),
            )
        }
    }

    fun startOrResume() {
        val uri = videoUri ?: return
        if (parts.isEmpty()) parts = buildParts()
        val folder = title.trim().replace(Regex("[^A-Za-z0-9 _-]"), "").ifBlank { "Reel" }
        splitJob = scope.launch {
            running = true
            message = null
            val total = parts.size
            for (part in parts) {
                if (part.status == PartStatus.DONE) continue
                parts = parts.map {
                    if (it.index == part.index) it.copy(status = PartStatus.WORKING, error = null)
                    else it
                }
                val result = runCatching {
                    val cacheFile = File(context.cacheDir, "part_${part.index}.mp4")
                    cacheFile.delete()
                    VideoSplitter.exportPart(
                        context = context,
                        input = uri,
                        outFile = cacheFile,
                        startMs = part.startMs,
                        endMs = part.endMs,
                        partNumber = part.index + 1,
                        totalParts = total,
                        reel = reel,
                    )
                    withContext(Dispatchers.IO) {
                        val name = "Part_%02d.mp4".format(part.index + 1)
                        VideoExport.saveVideoToMovies(context, folder, name, cacheFile)
                        cacheFile.delete()
                        VideoSplitter.thumbnailAt(context, uri, part.startMs)?.let { bitmap ->
                            VideoExport.saveThumbnail(
                                context, folder,
                                "Part_%02d.jpg".format(part.index + 1), bitmap,
                            )
                            bitmap.recycle()
                        }
                    }
                }
                var failed = false
                result.fold(
                    onSuccess = {
                        parts = parts.map {
                            if (it.index == part.index) it.copy(status = PartStatus.DONE) else it
                        }
                    },
                    onFailure = { e ->
                        parts = parts.map {
                            if (it.index == part.index) {
                                it.copy(status = PartStatus.ERROR, error = e.message)
                            } else it
                        }
                        message = e.message ?: "Export failed"
                        failed = true
                    },
                )
                if (failed) break
            }
            running = false
            if (parts.isNotEmpty() && parts.all { it.status == PartStatus.DONE }) {
                message = "All ${parts.size} parts saved to Movies/CloneCast/$folder ✓"
            }
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
    ) {
        Text(
            "Split for Reels",
            style = MaterialTheme.typography.headlineSmall,
            color = MaterialTheme.colorScheme.primary,
        )
        Spacer(Modifier.height(4.dp))
        Text(
            "Cut a long video into parts with Part 1/2/3 labels, " +
                "a 2-second recap overlap, and a thumbnail for each part.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(12.dp))

        Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
            OutlinedButton(
                onClick = { videoPicker.launch("video/*") },
                enabled = !running,
            ) { Text(if (videoUri == null) "🎬 Pick video" else "🎬 Change video") }
            Spacer(Modifier.width(12.dp))
            if (videoUri != null && durationMs > 0) {
                Text(
                    "%d:%02d min".format(durationMs / 60000, (durationMs / 1000) % 60),
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
        }

        if (videoUri != null && durationMs > 0) {
            Spacer(Modifier.height(12.dp))
            Text("Part length", style = MaterialTheme.typography.labelLarge)
            Spacer(Modifier.height(6.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf(30, 45, 60, 90).forEach { secs ->
                    FilterChip(
                        selected = !customMode && partSeconds == secs,
                        onClick = {
                            customMode = false
                            partSeconds = secs
                            parts = emptyList()
                        },
                        label = { Text("${secs}s") },
                        enabled = !running,
                    )
                }
                FilterChip(
                    selected = customMode,
                    onClick = { customMode = true; parts = emptyList() },
                    label = { Text("✏️ Custom") },
                    enabled = !running,
                )
            }
            if (customMode) {
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = customText,
                    onValueChange = { newValue ->
                        customText = newValue.filter { it.isDigit() }.take(4)
                        parts = emptyList()
                    },
                    label = { Text("Part length in seconds (5–3600)") },
                    placeholder = { Text("e.g. 120 for 2-minute parts") },
                    singleLine = true,
                    isError = customText.isNotEmpty() && !partLenValid,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    enabled = !running,
                    modifier = Modifier.fillMaxWidth(),
                )
            }

            Spacer(Modifier.height(12.dp))
            Text("Output format", style = MaterialTheme.typography.labelLarge)
            Spacer(Modifier.height(6.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(
                    selected = reel,
                    onClick = { reel = true; parts = emptyList() },
                    label = { Text("📱 Reel 9:16 (1080×1920)") },
                    enabled = !running,
                )
                FilterChip(
                    selected = !reel,
                    onClick = { reel = false; parts = emptyList() },
                    label = { Text("Original size") },
                    enabled = !running,
                )
            }

            Spacer(Modifier.height(12.dp))
            OutlinedTextField(
                value = title,
                onValueChange = { title = it },
                label = { Text("Folder name (e.g. drama episode name)") },
                singleLine = true,
                enabled = !running,
                modifier = Modifier.fillMaxWidth(),
            )

            if (partLenValid) {
                val partMs = effectiveSeconds * 1000L
                val total = ((durationMs + partMs - 1) / partMs).toInt()
                Text(
                    "≈ $total parts of ${effectiveSeconds}s each (Part 2 onward starts " +
                        "with a 2s recap of the previous part)",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 4.dp),
                )
            }

            Spacer(Modifier.height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                val hasWork = parts.isNotEmpty() && parts.any { it.status != PartStatus.DONE }
                Button(onClick = { startOrResume() }, enabled = !running && partLenValid) {
                    Text(
                        when {
                            running -> "Splitting…"
                            hasWork -> "Resume"
                            else -> "✂️ Split video"
                        },
                    )
                }
                if (running) {
                    OutlinedButton(
                        onClick = {
                            splitJob?.cancel()
                            running = false
                            message = "Stopped — tap Resume to continue"
                        },
                    ) { Text("Stop") }
                }
            }
            if (running) {
                Text(
                    "Keep the app open — best with the phone charging. " +
                        "Each part takes a little while to process.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 4.dp),
                )
            }
        }

        message?.let { msg ->
            Spacer(Modifier.height(8.dp))
            Text(
                msg,
                style = MaterialTheme.typography.bodySmall,
                color =
                    if (msg.contains("✓")) MaterialTheme.colorScheme.secondary
                    else MaterialTheme.colorScheme.error,
            )
        }

        if (parts.isNotEmpty()) {
            Spacer(Modifier.height(12.dp))
            val done = parts.count { it.status == PartStatus.DONE }
            Text("Parts: $done / ${parts.size} done", style = MaterialTheme.typography.labelLarge)
            Spacer(Modifier.height(6.dp))
            LazyColumn(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                items(parts, key = { it.index }) { part ->
                    Row(modifier = Modifier.fillMaxWidth()) {
                        Text(
                            when (part.status) {
                                PartStatus.PENDING -> "⏳"
                                PartStatus.WORKING -> "⚙️"
                                PartStatus.DONE -> "✅"
                                PartStatus.ERROR -> "❌"
                            },
                        )
                        Spacer(Modifier.width(8.dp))
                        Column {
                            Text(
                                "Part ${part.index + 1} — " +
                                    "%d:%02d to %d:%02d".format(
                                        part.startMs / 60000, (part.startMs / 1000) % 60,
                                        part.endMs / 60000, (part.endMs / 1000) % 60,
                                    ),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            part.error?.let { err ->
                                Text(
                                    err,
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.error,
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}
