package com.clonecast.app.ui

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.clonecast.app.audio.SamplePlayer
import com.clonecast.app.audio.SampleRecorder
import com.clonecast.app.audio.audioDurationSec
import com.clonecast.app.data.ProfileStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream

@Composable
fun RecordScreen(profileId: String, onBack: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val profiles by ProfileStore.profilesFlow(context).collectAsState(initial = emptyList())
    val profile = profiles.find { it.id == profileId }

    val recorder = remember { SampleRecorder(context) }
    val player = remember { SamplePlayer() }

    var hasPermission by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) ==
                PackageManager.PERMISSION_GRANTED,
        )
    }
    val permissionLauncher =
        rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            hasPermission = granted
        }

    var recording by remember { mutableStateOf(false) }
    var seconds by remember { mutableIntStateOf(0) }
    var level by remember { mutableFloatStateOf(0f) }
    var playing by remember { mutableStateOf(false) }
    var playPos by remember { mutableIntStateOf(0) }
    var recordError by remember { mutableStateOf<String?>(null) }

    val importLauncher =
        rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
            val target = profile
            if (uri != null && target != null) {
                player.stop()
                playing = false
                scope.launch {
                    val result = withContext(Dispatchers.IO) {
                        runCatching { importSample(context, uri, target.id) }
                    }
                    result.fold(
                        onSuccess = { file ->
                            recordError = null
                            ProfileStore.upsert(
                                context,
                                target.copy(samplePath = file.absolutePath, voiceId = null),
                            )
                        },
                        onFailure = {
                            recordError =
                                "Could not import that file — pick an MP3/WAV/M4A with clear speech."
                        },
                    )
                }
            }
        }

    LaunchedEffect(recording) {
        while (recording) {
            delay(200)
            val amp = recorder.maxAmplitude / 32767f
            level = maxOf(level * 0.6f, amp).coerceIn(0f, 1f)
        }
    }
    LaunchedEffect(recording) {
        while (recording) {
            delay(1000)
            seconds += 1
        }
    }
    LaunchedEffect(playing) {
        while (playing) {
            playPos = player.positionMs / 1000
            delay(200)
        }
        playPos = 0
    }
    DisposableEffect(Unit) {
        onDispose {
            if (recorder.isRecording) recorder.stop()
            player.stop()
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        if (profile == null) {
            Spacer(Modifier.height(48.dp))
            Text("Loading…", color = MaterialTheme.colorScheme.onSurfaceVariant)
            return@Column
        }

        // keyed on lastModified so a new take at the same path refreshes the duration
        val sampleStamp = profile.samplePath?.let { File(it).lastModified() } ?: 0L
        val sampleDuration = remember(profile.samplePath, sampleStamp) {
            profile.samplePath?.let(::audioDurationSec) ?: 0
        }

        Text(profile.genreEnum.emoji, fontSize = 44.sp)
        Text(
            profile.name,
            style = MaterialTheme.typography.headlineSmall,
            color = MaterialTheme.colorScheme.primary,
        )
        Text(
            profile.genreEnum.label + " style",
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        Spacer(Modifier.height(20.dp))
        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.surfaceVariant,
            ),
        ) {
            Column(Modifier.padding(16.dp)) {
                Text(
                    "🎤 How to record a good sample",
                    style = MaterialTheme.typography.labelLarge,
                )
                Spacer(Modifier.height(6.dp))
                Text(
                    "• Quiet room, phone ~30 cm from your mouth\n" +
                        "• Talk continuously for 1–3 minutes (read anything aloud)\n" +
                        "• ${profile.genreEnum.recordingTip}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        Spacer(Modifier.height(28.dp))
        val timerText = when {
            recording -> formatTime(seconds)
            playing -> formatTime(playPos) + " / " + formatTime(sampleDuration)
            profile.samplePath != null -> formatTime(sampleDuration)
            else -> "0:00"
        }
        Text(
            timerText,
            style = MaterialTheme.typography.displayMedium,
            color =
                if (recording && seconds < 60) MaterialTheme.colorScheme.error
                else if (recording || playing) MaterialTheme.colorScheme.secondary
                else MaterialTheme.colorScheme.onBackground,
        )
        if (!recording && !playing && profile.samplePath != null) {
            Text(
                "saved sample length",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        if (playing) {
            Text(
                "playing sample",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        if (recording) {
            Text(
                if (seconds < 60) "Keep going — aim for at least 1:00"
                else "Great length ✓ (stop anytime)",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(12.dp))
            LinearProgressIndicator(
                progress = { level },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(6.dp),
            )
            Text(
                "mic level",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        Spacer(Modifier.height(24.dp))

        if (!hasPermission) {
            Button(onClick = { permissionLauncher.launch(Manifest.permission.RECORD_AUDIO) }) {
                Text("Allow microphone access")
            }
        } else if (!recording) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Button(
                    onClick = {
                        player.stop()
                        playing = false
                        seconds = 0
                        level = 0f
                        recordError = null
                        runCatching { recorder.start(profile.id) }.fold(
                            onSuccess = { recording = true },
                            onFailure = {
                                recordError = "Could not start recording — is another app using the mic?"
                            },
                        )
                    },
                    colors = ButtonDefaults.buttonColors(
                        containerColor = MaterialTheme.colorScheme.error,
                    ),
                ) { Text(if (profile.samplePath == null) "●  Start recording" else "●  Re-record") }

                if (profile.samplePath != null) {
                    Spacer(Modifier.width(12.dp))
                    OutlinedButton(
                        onClick = {
                            if (playing) {
                                player.stop()
                                playing = false
                            } else {
                                playing = true
                                player.play(profile.samplePath) { playing = false }
                            }
                        },
                    ) { Text(if (playing) "■ Stop" else "▶ Play sample") }
                }
            }
        } else {
            Button(
                onClick = {
                    recording = false
                    val file = recorder.stop()
                    if (file != null) {
                        recordError = null
                        scope.launch {
                            ProfileStore.upsert(
                                context,
                                // re-recording invalidates any previous clone
                                profile.copy(samplePath = file.absolutePath, voiceId = null),
                            )
                        }
                    } else {
                        recordError =
                            "Recording failed — nothing was saved. Record for at least a few seconds and try again."
                    }
                },
            ) { Text("■  Stop & save") }
        }

        if (!recording) {
            Spacer(Modifier.height(10.dp))
            OutlinedButton(onClick = { importLauncher.launch("audio/*") }) {
                Text("📁 Upload audio instead")
            }
            Text(
                "MP3 / WAV / M4A — 1–3 min of clear speech in this genre's style",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        recordError?.let { message ->
            Spacer(Modifier.height(8.dp))
            Text(
                message,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
                textAlign = TextAlign.Center,
            )
        }
        if (profile.samplePath != null && !recording && recordError == null) {
            Spacer(Modifier.height(8.dp))
            Text(
                "Sample saved ✓",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.secondary,
            )
        }

        Spacer(Modifier.height(24.dp))
        TextButton(onClick = onBack) { Text("← Back to profiles") }
    }
}

private fun formatTime(totalSeconds: Int): String =
    "%d:%02d".format(totalSeconds / 60, totalSeconds % 60)

/** Copies a picked audio file into app storage as the profile's sample. */
private fun importSample(context: Context, uri: Uri, profileId: String): File {
    val resolver = context.contentResolver
    val mime = resolver.getType(uri).orEmpty()
    val ext = when {
        mime.contains("mpeg") || mime.contains("mp3") -> "mp3"
        mime.contains("wav") -> "wav"
        mime.contains("ogg") || mime.contains("opus") -> "ogg"
        mime.contains("flac") -> "flac"
        else -> "m4a"
    }
    val dir = File(context.filesDir, "samples").apply { mkdirs() }
    val tmp = File(dir, "$profileId.import.tmp")
    resolver.openInputStream(uri).use { input ->
        if (input == null) throw IllegalStateException("Cannot open the selected file")
        FileOutputStream(tmp).use { input.copyTo(it) }
    }
    if (tmp.length() < 4096) {
        tmp.delete()
        throw IllegalStateException("File is empty or too small")
    }
    val final = File(dir, "$profileId.$ext")
    // clear older sample files for this profile (any extension) before the swap
    dir.listFiles()?.forEach {
        if (it.name.startsWith("$profileId.") && it != tmp) it.delete()
    }
    return if (tmp.renameTo(final)) final else tmp
}
