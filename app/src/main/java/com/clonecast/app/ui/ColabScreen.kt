package com.clonecast.app.ui

import android.annotation.SuppressLint
import android.app.DownloadManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Environment
import android.webkit.URLUtil
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.compose.BackHandler
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
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import com.clonecast.app.data.SettingsStore
import kotlinx.coroutines.launch

private const val COLAB_NOTEBOOK_URL =
    "https://colab.research.google.com/github/R3gm/SoniTranslate/blob/main/SoniTranslate_Colab.ipynb"
private const val HF_DEMO_URL =
    "https://huggingface.co/spaces/r3gm/SoniTranslate_translate_audio_of_a_video_content"

@SuppressLint("SetJavaScriptEnabled")
@Composable
fun ColabScreen() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val storedLink by SettingsStore.colabLinkFlow(context).collectAsState(initial = "")
    var linkInput by remember(storedLink) { mutableStateOf(storedLink) }
    var activeUrl by remember { mutableStateOf<String?>(null) }
    var webView by remember { mutableStateOf<WebView?>(null) }
    var canGoBack by remember { mutableStateOf(false) }
    var pendingFileChooser by remember { mutableStateOf<ValueCallback<Array<Uri>>?>(null) }

    val fileChooserLauncher =
        rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            pendingFileChooser?.onReceiveValue(
                WebChromeClient.FileChooserParams.parseResult(result.resultCode, result.data),
            )
            pendingFileChooser = null
        }

    BackHandler(enabled = activeUrl != null && canGoBack) { webView?.goBack() }
    DisposableEffect(Unit) {
        onDispose { webView?.destroy() }
    }

    if (activeUrl == null) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
        ) {
            Text(
                "Colab Dub (SoniTranslate)",
                style = MaterialTheme.typography.headlineSmall,
                color = MaterialTheme.colorScheme.primary,
            )
            Text(
                "Free full auto-dub: keeps each character's ORIGINAL voice and " +
                    "auto-syncs timing. Runs on Google's free cloud, controlled from here.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(10.dp))

            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant,
                ),
            ) {
                Column(Modifier.padding(14.dp)) {
                    Text("How to start (one time per session)", style = MaterialTheme.typography.labelLarge)
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "1. Tap \"Open Colab notebook\" below — it opens in your browser\n" +
                            "2. Sign in with Google → menu: Runtime → Run all\n" +
                            "3. Wait ~5 minutes while it sets up (free GPU)\n" +
                            "4. At the bottom it prints a link like https://xxxx.gradio.live\n" +
                            "5. Copy that link, come back here, paste it and tap Connect",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            Spacer(Modifier.height(12.dp))
            Button(onClick = {
                context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(COLAB_NOTEBOOK_URL)))
            }) { Text("▶ Open Colab notebook") }

            Spacer(Modifier.height(12.dp))
            OutlinedTextField(
                value = linkInput,
                onValueChange = { linkInput = it },
                label = { Text("Paste the gradio.live link here") },
                placeholder = { Text("https://xxxx.gradio.live") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(8.dp))
            Row {
                Button(
                    onClick = {
                        val url = linkInput.trim()
                        scope.launch { SettingsStore.saveColabLink(context, url) }
                        activeUrl = url
                    },
                    enabled = linkInput.trim().startsWith("http"),
                ) { Text("Connect") }
                Spacer(Modifier.width(10.dp))
                OutlinedButton(onClick = { activeUrl = HF_DEMO_URL }) {
                    Text("Try demo (no setup)")
                }
            }

            Spacer(Modifier.height(14.dp))
            Text(
                "⚠️ Note: SoniTranslate's voice-clone model has a non-commercial " +
                    "license — fine for testing, grey zone for monetized videos. " +
                    "The Dub tab pipeline stays the clean option for the channel.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        }
    } else {
        Column(modifier = Modifier.fillMaxSize()) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 12.dp, vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    activeUrl.orEmpty().removePrefix("https://").take(34),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.weight(1f),
                )
                TextButton(onClick = {
                    webView?.destroy()
                    webView = null
                    activeUrl = null
                }) { Text("✕ Disconnect") }
            }
            key(activeUrl) {
                AndroidView(
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f),
                    factory = { ctx ->
                        WebView(ctx).apply {
                            settings.javaScriptEnabled = true
                            settings.domStorageEnabled = true
                            settings.allowFileAccess = true
                            settings.loadWithOverviewMode = true
                            settings.useWideViewPort = true
                            settings.mediaPlaybackRequiresUserGesture = false
                            webViewClient = object : WebViewClient() {
                                override fun onPageFinished(view: WebView?, url: String?) {
                                    canGoBack = view?.canGoBack() == true
                                }
                            }
                            webChromeClient = object : WebChromeClient() {
                                override fun onShowFileChooser(
                                    view: WebView?,
                                    filePathCallback: ValueCallback<Array<Uri>>?,
                                    fileChooserParams: FileChooserParams?,
                                ): Boolean {
                                    pendingFileChooser?.onReceiveValue(null)
                                    pendingFileChooser = filePathCallback
                                    return try {
                                        fileChooserLauncher.launch(fileChooserParams!!.createIntent())
                                        true
                                    } catch (e: Exception) {
                                        pendingFileChooser = null
                                        false
                                    }
                                }
                            }
                            setDownloadListener { url, _, contentDisposition, mimetype, _ ->
                                runCatching {
                                    val fileName =
                                        URLUtil.guessFileName(url, contentDisposition, mimetype)
                                    val request = DownloadManager.Request(Uri.parse(url))
                                        .setNotificationVisibility(
                                            DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED,
                                        )
                                        .setDestinationInExternalPublicDir(
                                            Environment.DIRECTORY_DOWNLOADS,
                                            fileName,
                                        )
                                    val dm = ctx.getSystemService(Context.DOWNLOAD_SERVICE)
                                        as DownloadManager
                                    dm.enqueue(request)
                                }
                            }
                            loadUrl(activeUrl.orEmpty())
                            webView = this
                        }
                    },
                )
            }
        }
    }
}
