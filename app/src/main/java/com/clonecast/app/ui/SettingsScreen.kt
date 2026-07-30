package com.clonecast.app.ui

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
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import com.clonecast.app.BuildConfig
import com.clonecast.app.convert.KaggleClient
import com.clonecast.app.data.KaggleStore
import com.clonecast.app.data.SettingsStore
import com.clonecast.app.tts.providerFor
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    val storedKey by SettingsStore.apiKeyFlow(context).collectAsState(initial = "")
    val storedProvider by SettingsStore.providerFlow(context)
        .collectAsState(initial = SettingsStore.PROVIDER_FISH)
    val storedGroqKey by SettingsStore.groqKeyFlow(context).collectAsState(initial = "")

    var keyInput by remember(storedKey) { mutableStateOf(storedKey) }
    var provider by remember(storedProvider) { mutableStateOf(storedProvider) }
    var groqInput by remember(storedGroqKey) { mutableStateOf(storedGroqKey) }
    var showKey by remember { mutableStateOf(false) }
    var showGroqKey by remember { mutableStateOf(false) }
    var menuOpen by remember { mutableStateOf(false) }
    var testing by remember { mutableStateOf(false) }
    var testResult by remember { mutableStateOf<String?>(null) }
    var testOk by remember { mutableStateOf(false) }
    var saved by remember { mutableStateOf(false) }

    val providerNames = mapOf(
        SettingsStore.PROVIDER_FISH to "Fish Audio",
        SettingsStore.PROVIDER_ELEVENLABS to "ElevenLabs",
    )

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
    ) {
        Text(
            "Settings",
            style = MaterialTheme.typography.headlineMedium,
            color = MaterialTheme.colorScheme.primary,
        )
        Spacer(Modifier.height(24.dp))

        Text("Voice provider", style = MaterialTheme.typography.labelLarge)
        Spacer(Modifier.height(8.dp))
        ExposedDropdownMenuBox(expanded = menuOpen, onExpandedChange = { menuOpen = it }) {
            OutlinedTextField(
                value = providerNames[provider] ?: provider,
                onValueChange = {},
                readOnly = true,
                trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = menuOpen) },
                modifier = Modifier
                    .fillMaxWidth()
                    .menuAnchor(),
            )
            ExposedDropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                providerNames.forEach { (id, name) ->
                    DropdownMenuItem(
                        text = { Text(name) },
                        onClick = {
                            provider = id
                            menuOpen = false
                            testResult = null
                        },
                    )
                }
            }
        }

        Spacer(Modifier.height(20.dp))
        Text("API key", style = MaterialTheme.typography.labelLarge)
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            value = keyInput,
            onValueChange = { keyInput = it; saved = false; testResult = null },
            placeholder = { Text("Paste your API key here") },
            singleLine = true,
            visualTransformation =
                if (showKey) VisualTransformation.None else PasswordVisualTransformation(),
            trailingIcon = {
                TextButton(onClick = { showKey = !showKey }) {
                    Text(if (showKey) "Hide" else "Show")
                }
            },
            modifier = Modifier.fillMaxWidth(),
        )
        Text(
            "Stored only on this phone. Get it from fish.audio → API keys.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 4.dp),
        )

        Spacer(Modifier.height(20.dp))
        Text("Groq API key — free audio → text", style = MaterialTheme.typography.labelLarge)
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            value = groqInput,
            onValueChange = { groqInput = it; saved = false },
            placeholder = { Text("Optional — for 'Script from audio'") },
            singleLine = true,
            visualTransformation =
                if (showGroqKey) VisualTransformation.None else PasswordVisualTransformation(),
            trailingIcon = {
                TextButton(onClick = { showGroqKey = !showGroqKey }) {
                    Text(if (showGroqKey) "Hide" else "Show")
                }
            },
            modifier = Modifier.fillMaxWidth(),
        )
        Text(
            "Free key from console.groq.com (no card needed) — speak your recap, " +
                "the app turns it into script text.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 4.dp),
        )

        Spacer(Modifier.height(24.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Button(
                onClick = {
                    scope.launch {
                        SettingsStore.save(context, keyInput.trim(), provider, groqInput.trim())
                        saved = true
                    }
                },
                enabled = keyInput.isNotBlank() || groqInput.isNotBlank(),
            ) { Text(if (saved) "Saved ✓" else "Save") }

            Spacer(Modifier.width(12.dp))

            OutlinedButton(
                onClick = {
                    scope.launch {
                        testing = true
                        testResult = null
                        val result = providerFor(provider).checkConnection(keyInput.trim())
                        testOk = result.isSuccess
                        testResult = result.getOrElse { it.message ?: "Connection failed" }
                        testing = false
                    }
                },
                enabled = keyInput.isNotBlank() && !testing,
            ) { Text("Test connection") }

            if (testing) {
                Spacer(Modifier.width(12.dp))
                CircularProgressIndicator(modifier = Modifier.width(20.dp).height(20.dp), strokeWidth = 2.dp)
            }
        }

        testResult?.let { message ->
            Spacer(Modifier.height(16.dp))
            Text(
                message,
                style = MaterialTheme.typography.bodyMedium,
                color = if (testOk) MaterialTheme.colorScheme.secondary
                        else MaterialTheme.colorScheme.error,
            )
        }

        Spacer(Modifier.height(28.dp))
        KaggleSection()

        Spacer(Modifier.height(32.dp))
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(
                "How to get a Fish Audio key",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                "1. Sign up at fish.audio\n" +
                "2. Go to API → create API key\n" +
                "3. Top up a small credit (₹400–₹850 / \$5–\$10 lasts many videos)\n" +
                "4. Paste the key above, Save, then Test connection",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        Spacer(Modifier.height(24.dp))
        Text(
            "CloneCast v" + BuildConfig.VERSION_NAME,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
        )
    }
}

@Composable
private fun KaggleSection() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    val storedUser by KaggleStore.usernameFlow(context).collectAsState(initial = "")
    val storedKaggleKey by KaggleStore.apiKeyFlow(context).collectAsState(initial = "")

    var userInput by remember(storedUser) { mutableStateOf(storedUser) }
    var kaggleKeyInput by remember(storedKaggleKey) { mutableStateOf(storedKaggleKey) }
    var showKaggleKey by remember { mutableStateOf(false) }
    var kaggleSaved by remember { mutableStateOf(false) }
    var kaggleTesting by remember { mutableStateOf(false) }
    var kaggleTestOk by remember { mutableStateOf(false) }
    var kaggleTestResult by remember { mutableStateOf<String?>(null) }

    Text("Kaggle — free GPU voice convert", style = MaterialTheme.typography.labelLarge)
    Spacer(Modifier.height(8.dp))
    OutlinedTextField(
        value = userInput,
        onValueChange = { userInput = it; kaggleSaved = false; kaggleTestResult = null },
        label = { Text("Kaggle username") },
        singleLine = true,
        modifier = Modifier.fillMaxWidth(),
    )
    Spacer(Modifier.height(8.dp))
    OutlinedTextField(
        value = kaggleKeyInput,
        onValueChange = {
            // Convenience: pasting the whole kaggle.json fills both fields.
            val pasted = it.trim()
            if (pasted.startsWith("{") && pasted.contains("\"key\"")) {
                Regex("\"username\"\\s*:\\s*\"([^\"]+)\"").find(pasted)
                    ?.groupValues?.get(1)?.let { u -> userInput = u }
                kaggleKeyInput = Regex("\"key\"\\s*:\\s*\"([^\"]+)\"").find(pasted)
                    ?.groupValues?.get(1) ?: pasted
            } else {
                kaggleKeyInput = it
            }
            kaggleSaved = false
            kaggleTestResult = null
        },
        label = { Text("Kaggle API key (or paste kaggle.json)") },
        singleLine = true,
        visualTransformation =
            if (showKaggleKey) VisualTransformation.None else PasswordVisualTransformation(),
        trailingIcon = {
            TextButton(onClick = { showKaggleKey = !showKaggleKey }) {
                Text(if (showKaggleKey) "Hide" else "Show")
            }
        },
        modifier = Modifier.fillMaxWidth(),
    )
    Text(
        "kaggle.com → Settings → API → Create New Token. Stored encrypted on this " +
            "phone only. Note: creating a new token expires the old one — if your PC " +
            "pipeline uses one, paste that same key instead of making a new token.",
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(top = 4.dp),
    )
    Spacer(Modifier.height(12.dp))
    Row(verticalAlignment = Alignment.CenterVertically) {
        Button(
            onClick = {
                scope.launch {
                    KaggleStore.saveCreds(context, userInput, kaggleKeyInput)
                    kaggleSaved = true
                }
            },
            enabled = userInput.isNotBlank() && kaggleKeyInput.isNotBlank(),
        ) { Text(if (kaggleSaved) "Saved ✓" else "Save Kaggle") }

        Spacer(Modifier.width(12.dp))

        OutlinedButton(
            onClick = {
                scope.launch {
                    kaggleTesting = true
                    kaggleTestResult = null
                    val result = KaggleClient.gpuQuota(
                        KaggleClient.Creds(userInput.trim(), kaggleKeyInput.trim()),
                    )
                    kaggleTestOk = result.isSuccess
                    kaggleTestResult = result.fold(
                        onSuccess = { quota ->
                            KaggleStore.saveCreds(context, userInput, kaggleKeyInput)
                            kaggleSaved = true
                            val usedH = quota.usedSeconds / 3600f
                            val totalH = quota.totalSeconds / 3600f
                            if (quota.totalSeconds > 0) {
                                "Connected ✓  GPU quota: %.1f / %.0f hrs used this week"
                                    .format(usedH, totalH)
                            } else {
                                "Connected ✓"
                            }
                        },
                        onFailure = { it.message ?: "Connection failed" },
                    )
                    kaggleTesting = false
                }
            },
            enabled = userInput.isNotBlank() && kaggleKeyInput.isNotBlank() && !kaggleTesting,
        ) { Text("Test") }

        if (kaggleTesting) {
            Spacer(Modifier.width(12.dp))
            CircularProgressIndicator(modifier = Modifier.width(20.dp).height(20.dp), strokeWidth = 2.dp)
        }
    }

    kaggleTestResult?.let { message ->
        Spacer(Modifier.height(8.dp))
        Text(
            message,
            style = MaterialTheme.typography.bodyMedium,
            color = if (kaggleTestOk) MaterialTheme.colorScheme.secondary
                    else MaterialTheme.colorScheme.error,
        )
    }
}
