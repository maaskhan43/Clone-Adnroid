package com.clonecast.app.ui

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
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
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import com.clonecast.app.convert.ConvertManager
import com.clonecast.app.data.AudioExport
import com.clonecast.app.data.ConvertStage
import com.clonecast.app.data.KaggleStore
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@Composable
private fun TrainingCard() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var status by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var confirmTrain by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        status = ConvertManager.trainingStatus(context).getOrElse { it.message }
    }

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant,
        ),
    ) {
        Column(Modifier.padding(12.dp)) {
            Text("Voice model (one-time)", style = MaterialTheme.typography.labelLarge)
            Spacer(Modifier.height(4.dp))
            Text(
                status ?: "Checking…",
                style = MaterialTheme.typography.bodySmall,
                color = if (status?.startsWith("READY") == true) {
                    MaterialTheme.colorScheme.secondary
                } else {
                    MaterialTheme.colorScheme.onSurfaceVariant
                },
            )
            Spacer(Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (status?.startsWith("READY") != true) {
                    Button(
                        onClick = { confirmTrain = true },
                        enabled = !busy,
                    ) { Text("Train voice model") }
                    Spacer(Modifier.width(10.dp))
                }
                OutlinedButton(
                    onClick = {
                        scope.launch {
                            busy = true
                            status = ConvertManager.trainingStatus(context)
                                .getOrElse { it.message }
                            busy = false
                        }
                    },
                    enabled = !busy,
                ) { Text("Refresh") }
                if (busy) {
                    Spacer(Modifier.width(10.dp))
                    CircularProgressIndicator(
                        modifier = Modifier.width(18.dp).height(18.dp),
                        strokeWidth = 2.dp,
                    )
                }
            }
            if (confirmTrain) {
                Spacer(Modifier.height(8.dp))
                Text(
                    "Starts a ~1 hour free GPU run on Kaggle using your " +
                        "clonecast-voice-raw audio. Don't open kaggle.com while it runs.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(6.dp))
                Row {
                    Button(onClick = {
                        confirmTrain = false
                        scope.launch {
                            busy = true
                            val result = ConvertManager.startTraining(context)
                            status = result.fold(
                                onSuccess = { "Training started — tap Refresh for status (~40-60 min)" },
                                onFailure = { it.message ?: "Could not start training" },
                            )
                            busy = false
                        }
                    }) { Text("Start now") }
                    Spacer(Modifier.width(10.dp))
                    TextButton(onClick = { confirmTrain = false }) { Text("Cancel") }
                }
            }
        }
    }
}

private fun stageLabel(stage: ConvertStage?): String = when (stage) {
    ConvertStage.UPLOADING -> "1/5 Uploading"
    ConvertStage.WAITING_DATASET -> "1/5 Processing upload"
    ConvertStage.PUSHING -> "2/5 Starting GPU"
    ConvertStage.RUNNING -> "3/5 Converting"
    ConvertStage.DOWNLOADING -> "4/5 Downloading"
    ConvertStage.SAVING -> "5/5 Saving"
    ConvertStage.DONE -> "Done ✓"
    ConvertStage.ERROR -> "Failed"
    ConvertStage.CANCELED -> "Canceled"
    null -> ""
}

@Composable
fun ConvertScreen() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    val username by KaggleStore.usernameFlow(context).collectAsState(initial = "")
    val jobs by KaggleStore.jobsFlow(context).collectAsState(initial = emptyList())
    val progress by ConvertManager.progress.collectAsState()

    var pickedUri by remember { mutableStateOf<Uri?>(null) }
    var pickedName by remember { mutableStateOf("") }
    var title by remember { mutableStateOf("") }
    var startError by remember { mutableStateOf<String?>(null) }

    val activeJob = jobs.firstOrNull { !it.stage.isTerminal }

    LaunchedEffect(Unit) { ConvertManager.resume(context) }

    val picker = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument(),
    ) { uri ->
        if (uri != null) {
            pickedUri = uri
            pickedName = uri.lastPathSegment?.substringAfterLast('/') ?: "audio"
            startError = null
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
    ) {
        Text(
            "Convert (RVC)",
            style = MaterialTheme.typography.headlineSmall,
            color = MaterialTheme.colorScheme.primary,
        )
        Text(
            "Audio → audio in your cloned voice. Same length, same pauses — " +
                "record the narration yourself, this only changes the voice. Free on Kaggle GPU.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(12.dp))

        if (username.isBlank()) {
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.errorContainer,
                ),
            ) {
                Text(
                    "Add your Kaggle username & API key in Settings first " +
                        "(kaggle.com → Settings → Create New Token).",
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.padding(12.dp),
                )
            }
            Spacer(Modifier.height(12.dp))
        } else {
            TrainingCard()
            Spacer(Modifier.height(12.dp))
        }

        if (activeJob == null) {
            OutlinedButton(onClick = { picker.launch(arrayOf("audio/*")) }) {
                Text(if (pickedUri == null) "Pick narration audio…" else "✓ $pickedName")
            }
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = title,
                onValueChange = { title = it },
                label = { Text("Output name") },
                placeholder = { Text("ep12-recap") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(12.dp))
            Button(
                onClick = {
                    val uri = pickedUri ?: return@Button
                    scope.launch {
                        startError = null
                        val result = ConvertManager.start(context, uri, title.trim())
                        result.exceptionOrNull()?.let { startError = it.message }
                        if (result.isSuccess) {
                            pickedUri = null
                            pickedName = ""
                            title = ""
                        }
                    }
                },
                enabled = pickedUri != null && username.isNotBlank(),
            ) { Text("Convert on Kaggle T4") }

            startError?.let {
                Spacer(Modifier.height(8.dp))
                Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium)
            }
            Spacer(Modifier.height(8.dp))
            Text(
                "Takes ~10-20 min (free GPU spin-up + convert). Keep the app open during " +
                    "upload; after that Kaggle does the work and you can come back later.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else {
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(Modifier.padding(14.dp)) {
                    Text(activeJob.title, style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(6.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        CircularProgressIndicator(
                            modifier = Modifier.width(18.dp).height(18.dp),
                            strokeWidth = 2.dp,
                        )
                        Spacer(Modifier.width(10.dp))
                        Text(
                            stageLabel(progress.stage ?: activeJob.stage),
                            style = MaterialTheme.typography.labelLarge,
                        )
                    }
                    if (progress.detail.isNotBlank()) {
                        Spacer(Modifier.height(4.dp))
                        Text(
                            progress.detail,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    progress.fraction?.let { f ->
                        Spacer(Modifier.height(8.dp))
                        LinearProgressIndicator(
                            progress = { f },
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                    Spacer(Modifier.height(10.dp))
                    TextButton(onClick = { scope.launch { ConvertManager.cancel(context) } }) {
                        Text("Cancel", color = MaterialTheme.colorScheme.error)
                    }
                }
            }
        }

        if (jobs.isNotEmpty()) {
            Spacer(Modifier.height(20.dp))
            Text("History", style = MaterialTheme.typography.labelLarge)
            Spacer(Modifier.height(6.dp))
            val dateFormat = remember { SimpleDateFormat("dd MMM HH:mm", Locale.getDefault()) }
            jobs.filter { it.stage.isTerminal }.take(10).forEach { job ->
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 4.dp),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surfaceVariant,
                    ),
                ) {
                    Row(
                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(job.title, style = MaterialTheme.typography.bodyMedium)
                            Text(
                                "${stageLabel(job.stage)} · ${dateFormat.format(Date(job.updatedAt))}" +
                                    " · ${job.inputDurationMs / 60000} min",
                                style = MaterialTheme.typography.bodySmall,
                                color = if (job.stage == ConvertStage.ERROR) {
                                    MaterialTheme.colorScheme.error
                                } else {
                                    MaterialTheme.colorScheme.onSurfaceVariant
                                },
                            )
                            if (job.stage == ConvertStage.ERROR && job.error != null) {
                                Text(
                                    job.error.take(160),
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.error,
                                )
                            }
                        }
                        if (job.stage == ConvertStage.DONE && job.outputUri != null) {
                            TextButton(onClick = {
                                AudioExport.share(context, Uri.parse(job.outputUri))
                            }) { Text("Share") }
                        }
                    }
                }
            }
        }
    }
}
