package com.clonecast.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
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
import com.clonecast.app.data.Genre
import com.clonecast.app.data.ProfileStore
import com.clonecast.app.data.SettingsStore
import com.clonecast.app.data.VoiceProfile
import com.clonecast.app.tts.providerFor
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import java.io.File
import java.util.UUID

@Composable
fun ProfilesScreen(onRecord: (String) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val profiles by ProfileStore.profilesFlow(context).collectAsState(initial = emptyList())

    var showCreate by remember { mutableStateOf(false) }
    var consentFor by remember { mutableStateOf<VoiceProfile?>(null) }
    var cloningId by remember { mutableStateOf<String?>(null) }
    var statusById by remember { mutableStateOf<Map<String, String>>(emptyMap()) }

    fun startClone(profile: VoiceProfile) {
        val samplePath = profile.samplePath ?: return
        scope.launch {
            val key = SettingsStore.apiKeyFlow(context).first().trim()
            val providerId = SettingsStore.providerFlow(context).first()
            if (key.isBlank()) {
                statusById = statusById + (profile.id to "Add your API key in Settings first")
                return@launch
            }
            cloningId = profile.id
            statusById = statusById - profile.id
            val result = providerFor(providerId)
                .cloneVoice(key, profile.name, File(samplePath))
            result.fold(
                onSuccess = { voiceId ->
                    ProfileStore.upsert(context, profile.copy(voiceId = voiceId))
                    statusById = statusById + (profile.id to "Cloned successfully ✓")
                },
                onFailure = { e ->
                    statusById = statusById + (profile.id to (e.message ?: "Cloning failed"))
                },
            )
            cloningId = null
        }
    }

    Scaffold(
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = { showCreate = true },
                icon = { Icon(Icons.Filled.Add, contentDescription = null) },
                text = { Text("New voice") },
            )
        },
    ) { padding ->
        if (profiles.isEmpty()) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .padding(24.dp),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text("🎭", fontSize = 48.sp)
                Spacer(Modifier.height(12.dp))
                Text(
                    "No voices yet",
                    style = MaterialTheme.typography.headlineSmall,
                    color = MaterialTheme.colorScheme.primary,
                )
                Spacer(Modifier.height(8.dp))
                Text(
                    "Create one voice per genre — record yourself acting that mood " +
                        "(playful for comedy, whispery for horror…) and the clone " +
                        "keeps that style.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                )
            }
        } else {
            LazyColumn(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                items(profiles, key = { it.id }) { profile ->
                    ProfileCard(
                        profile = profile,
                        cloning = cloningId == profile.id,
                        status = statusById[profile.id],
                        onRecord = { onRecord(profile.id) },
                        onClone = { consentFor = profile },
                        onDelete = {
                            scope.launch {
                                profile.samplePath?.let { File(it).delete() }
                                ProfileStore.delete(context, profile.id)
                            }
                        },
                    )
                }
            }
        }
    }

    if (showCreate) {
        CreateProfileDialog(
            onDismiss = { showCreate = false },
            onCreate = { name, genre, gender, pastedVoiceId ->
                showCreate = false
                scope.launch {
                    ProfileStore.upsert(
                        context,
                        VoiceProfile(
                            id = UUID.randomUUID().toString(),
                            name = name,
                            genre = genre.name,
                            gender = gender,
                            voiceId = pastedVoiceId,
                        ),
                    )
                }
            },
        )
    }

    consentFor?.let { profile ->
        AlertDialog(
            onDismissRequest = { consentFor = null },
            title = { Text("Clone this voice?") },
            text = {
                Text(
                    "The recorded sample will be uploaded to your voice provider to " +
                        "create the clone.\n\nBy continuing you confirm this is YOUR OWN " +
                        "voice and you consent to cloning it. Cloning someone else's " +
                        "voice without permission is not allowed.",
                )
            },
            confirmButton = {
                Button(
                    onClick = {
                        consentFor = null
                        startClone(profile)
                    },
                ) { Text("It's my voice — Clone") }
            },
            dismissButton = {
                TextButton(onClick = { consentFor = null }) { Text("Cancel") }
            },
        )
    }
}

@Composable
private fun ProfileCard(
    profile: VoiceProfile,
    cloning: Boolean,
    status: String?,
    onRecord: () -> Unit,
    onClone: () -> Unit,
    onDelete: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    ) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(profile.genreEnum.emoji, fontSize = 28.sp)
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Text(profile.name, style = MaterialTheme.typography.titleMedium)
                    Text(
                        profile.genreEnum.label,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.primary,
                    )
                    val statusLine = when {
                        cloning -> "Cloning… (takes a moment)"
                        profile.voiceId != null -> "Cloned ✓ — ready to generate"
                        profile.samplePath != null -> "Sample recorded — tap Clone"
                        else -> "No sample yet — tap Record"
                    }
                    Text(
                        statusLine,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                IconButton(onClick = onDelete) {
                    Icon(
                        Icons.Filled.Delete,
                        contentDescription = "Delete",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = onRecord, enabled = !cloning) {
                    Text(if (profile.samplePath == null) "Record" else "Re-record")
                }
                if (profile.samplePath != null && profile.voiceId == null) {
                    Button(onClick = onClone, enabled = !cloning) {
                        Text(if (cloning) "Cloning…" else "Clone voice")
                    }
                }
            }
            status?.let { message ->
                Spacer(Modifier.height(6.dp))
                Text(
                    message,
                    style = MaterialTheme.typography.bodySmall,
                    color =
                        if (message.contains("✓")) MaterialTheme.colorScheme.secondary
                        else MaterialTheme.colorScheme.error,
                )
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun CreateProfileDialog(
    onDismiss: () -> Unit,
    onCreate: (String, Genre, String, String?) -> Unit,
) {
    var name by remember { mutableStateOf("") }
    var genre by remember { mutableStateOf(Genre.DRAMA) }
    var gender by remember { mutableStateOf("male") }
    var pastedId by remember { mutableStateOf("") }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("New voice profile") },
        text = {
            Column {
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    placeholder = { Text("e.g. My Drama Voice") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(12.dp))
                Text("Voice gender", style = MaterialTheme.typography.labelLarge)
                Spacer(Modifier.height(6.dp))
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FilterChip(
                        selected = gender == "male",
                        onClick = { gender = "male" },
                        label = { Text("♂ Male") },
                    )
                    FilterChip(
                        selected = gender == "female",
                        onClick = { gender = "female" },
                        label = { Text("♀ Female") },
                    )
                }
                Spacer(Modifier.height(12.dp))
                Text("Genre style", style = MaterialTheme.typography.labelLarge)
                Spacer(Modifier.height(6.dp))
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Genre.entries.forEach { g ->
                        FilterChip(
                            selected = genre == g,
                            onClick = { genre = g },
                            label = { Text("${g.emoji} ${g.label}") },
                        )
                    }
                }
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    value = pastedId,
                    onValueChange = { pastedId = it },
                    label = { Text("Voice ID (optional)") },
                    placeholder = { Text("Paste from fish.audio library — no recording needed") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        },
        confirmButton = {
            Button(
                onClick = {
                    onCreate(
                        name.trim().ifBlank { genre.label + " Voice" },
                        genre,
                        gender,
                        pastedId.trim().ifBlank { null },
                    )
                },
            ) { Text("Create") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel") }
        },
    )
}
