package com.clonecast.app.convert

import android.content.ContentValues
import android.content.Context
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import androidx.core.content.FileProvider
import com.clonecast.app.data.ConvertJob
import com.clonecast.app.data.ConvertStage
import com.clonecast.app.data.KaggleStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.security.MessageDigest
import java.util.UUID

/** Live progress the Convert screen renders. */
data class ConvertProgress(
    val runId: String? = null,
    val stage: ConvertStage? = null,
    val detail: String = "",
    val fraction: Float? = null,
)

/**
 * Resumable conversion state machine (plan section 3):
 * UPLOADING -> WAITING_DATASET -> PUSHING -> RUNNING -> DOWNLOADING -> SAVING -> DONE.
 *
 * Single-flight: fixed clonecast-* slugs mean only ONE active job per account
 * (guardrail 5). A Mutex guards starts; extra requests are rejected with a
 * clear message instead of silently overwriting the active run.
 *
 * The heavy work happens on Kaggle, so process death is safe: every stage
 * transition is persisted, and resume() continues from the saved stage.
 */
object ConvertManager {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val startLock = Mutex()
    private var activeWork: Job? = null
    private val json = Json { ignoreUnknownKeys = true }

    private val _progress = MutableStateFlow(ConvertProgress())
    val progress: StateFlow<ConvertProgress> = _progress

    private const val POLL_INTERVAL_MS = 30_000L
    private const val DATASET_TIMEOUT_MS = 10 * 60_000L
    private const val KERNEL_TIMEOUT_MS = 120 * 60_000L

    /** Copies the picked audio into app storage and starts (or rejects) a job. */
    suspend fun start(context: Context, sourceUri: Uri, title: String): Result<String> =
        startLock.withLock {
            runCatching {
                val jobs = KaggleStore.currentJobs(context)
                jobs.firstOrNull { !it.stage.isTerminal }?.let {
                    throw IllegalStateException(
                        "A conversion is already running (${it.title}). " +
                            "Wait for it to finish — one at a time keeps Kaggle runs safe.",
                    )
                }
                val creds = credsOrThrow(context)
                val runId = UUID.randomUUID().toString().replace("-", "").take(16)

                val dir = File(context.filesDir, "convert").apply { mkdirs() }
                val ext = context.contentResolver.getType(sourceUri)
                    ?.substringAfterLast('/')?.takeIf { it.length in 2..4 } ?: "m4a"
                val input = File(dir, "input_$runId.$ext")
                context.contentResolver.openInputStream(sourceUri)?.use { stream ->
                    input.outputStream().use { stream.copyTo(it) }
                } ?: throw IllegalStateException("Could not read the selected audio file")

                val durationMs = audioDurationMs(input)
                if (durationMs < 1_000) throw IllegalStateException("Audio too short or unreadable")

                val job = ConvertJob(
                    runId = runId,
                    title = title.ifBlank { "narration" },
                    inputPath = input.absolutePath,
                    inputSha256 = sha256(input),
                    inputDurationMs = durationMs,
                    kaggleUser = creds.username,
                    createdAt = System.currentTimeMillis(),
                    updatedAt = System.currentTimeMillis(),
                )
                KaggleStore.upsertJob(context, job)
                launchStateMachine(context, job)
                runId
            }
        }

    /** Continues a non-terminal job after app restart. No-op when nothing to resume. */
    fun resume(context: Context) {
        scope.launch {
            startLock.withLock {
                if (activeWork?.isActive == true) return@withLock
                val job = KaggleStore.currentJobs(context).firstOrNull { !it.stage.isTerminal }
                    ?: return@withLock
                launchStateMachine(context, job)
            }
        }
    }

    /** Local cancel: stops driving the job. A kernel already pushed keeps running on Kaggle. */
    suspend fun cancel(context: Context) {
        // Same lock as start()/resume(): otherwise a concurrent resume() can observe
        // the job still non-terminal and relaunch a duplicate state machine.
        startLock.withLock {
            activeWork?.cancelAndJoin()
            activeWork = null
            val job = KaggleStore.currentJobs(context).firstOrNull { !it.stage.isTerminal }
                ?: return@withLock
            persist(
                context,
                job.copy(
                    stage = ConvertStage.CANCELED,
                    error = "Canceled from the app. If the Kaggle run already started it " +
                        "will still finish there and count against quota.",
                ),
            )
            _progress.value = ConvertProgress(job.runId, ConvertStage.CANCELED, "Canceled")
        }
    }

    private suspend fun credsOrThrow(context: Context): KaggleClient.Creds {
        val username = KaggleStore.usernameFlow(context).first()
        val apiKey = KaggleStore.apiKeyFlow(context).first()
        if (username.isBlank() || apiKey.isBlank()) {
            throw IllegalStateException("Add your Kaggle username & API key in Settings first")
        }
        return KaggleClient.Creds(username, apiKey)
    }

    private fun launchStateMachine(context: Context, startJob: ConvertJob) {
        activeWork = scope.launch {
            var job = startJob
            try {
                val creds = credsOrThrow(context)
                if (creds.username != job.kaggleUser) {
                    throw IllegalStateException(
                        "This job belongs to Kaggle account '${job.kaggleUser}' but " +
                            "Settings now has '${creds.username}'. Cancel it and start again.",
                    )
                }
                // Stages before PUSHING restart from UPLOADING (blob tokens are not
                // resumable); PUSHING onward resumes in place — the kernel is the
                // durable state on Kaggle's side.
                if (job.stage == ConvertStage.WAITING_DATASET) {
                    job = persist(context, job.copy(stage = ConvertStage.UPLOADING))
                }
                if (job.stage == ConvertStage.UPLOADING) {
                    uploadInput(context, creds, job)
                    job = persist(context, job.copy(stage = ConvertStage.WAITING_DATASET))
                    waitDatasetReady(creds, job)
                    job = persist(context, job.copy(stage = ConvertStage.PUSHING))
                }
                if (job.stage == ConvertStage.PUSHING) {
                    pushKernel(context, creds, job)
                    job = persist(context, job.copy(stage = ConvertStage.RUNNING))
                }
                if (job.stage == ConvertStage.RUNNING) {
                    val status = pollKernel(context, creds, job)
                    job = persist(context, job.copy(stage = ConvertStage.DOWNLOADING, kaggleStatus = status))
                }
                // SAVING included: process death between the SAVING persist and the
                // MediaStore write would otherwise leave the job stuck forever.
                // downloadOutput is idempotent (re-download + sha/run_id checks).
                if (job.stage == ConvertStage.DOWNLOADING || job.stage == ConvertStage.SAVING) {
                    val mp3 = downloadOutput(context, creds, job)
                    job = persist(context, job.copy(stage = ConvertStage.SAVING))
                    // Idempotent save: drop any export left from a previous attempt
                    // (pending or finalized) so a resume never duplicates the file.
                    job.pendingOutputUri?.let { stale ->
                        // Clear the pointer only after the stale row is really gone —
                        // otherwise a failed delete orphans it and the retry duplicates.
                        runCatching { context.contentResolver.delete(Uri.parse(stale), null, null) }
                            .getOrElse {
                                throw IllegalStateException(
                                    "Could not clean up the previous export — retry the conversion",
                                )
                            }
                        job = persist(context, job.copy(pendingOutputUri = null))
                    }
                    val uri = if (Build.VERSION.SDK_INT >= 29) {
                        val pending = createPendingAudio(context, job.title)
                        job = persist(context, job.copy(pendingOutputUri = pending.toString()))
                        finalizePendingAudio(context, pending, mp3)
                        pending
                    } else {
                        // Pre-29: per-run file path — retries reuse it, separate runs never collide.
                        saveToMusicLegacy(context, job.title, job.runId, mp3)
                    }
                    mp3.delete()
                    File(job.inputPath).delete()
                    job = persist(
                        context,
                        job.copy(
                            stage = ConvertStage.DONE,
                            outputUri = uri.toString(),
                            pendingOutputUri = null,
                        ),
                    )
                    _progress.value = ConvertProgress(job.runId, ConvertStage.DONE, "Saved to Music/CloneCast")
                }
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                val message = e.message ?: "Conversion failed"
                persist(context, job.copy(stage = ConvertStage.ERROR, error = message))
                _progress.value = ConvertProgress(job.runId, ConvertStage.ERROR, message)
            }
        }
    }

    private suspend fun persist(context: Context, job: ConvertJob): ConvertJob {
        val updated = job.copy(updatedAt = System.currentTimeMillis())
        KaggleStore.upsertJob(context, updated)
        return updated
    }

    private fun report(job: ConvertJob, stage: ConvertStage, detail: String, fraction: Float? = null) {
        _progress.value = ConvertProgress(job.runId, stage, detail, fraction)
    }

    // --- Stage implementations ---

    private suspend fun uploadInput(context: Context, creds: KaggleClient.Creds, job: ConvertJob) {
        val input = File(job.inputPath)
        if (!input.isFile) throw IllegalStateException("Input file lost — start the conversion again")
        report(job, ConvertStage.UPLOADING, "Uploading audio (${input.length() / 1_048_576} MB)…", 0f)

        val audioToken = KaggleClient.uploadBlob(creds, input, audioMime(input)) { f ->
            report(job, ConvertStage.UPLOADING, "Uploading audio…", f)
        }.getOrThrow()

        val jobFile = File(context.cacheDir, "job.json").apply {
            writeText(RvcAssets.jobJson(job.runId, job.inputSha256, job.inputDurationMs, input.name))
        }
        val jobToken = KaggleClient.uploadBlob(creds, jobFile, "application/json").getOrThrow()
        jobFile.delete()

        report(job, ConvertStage.UPLOADING, "Creating dataset version…")
        val tokens = listOf(audioToken, jobToken)
        val version = KaggleClient.versionDataset(
            creds, RvcAssets.INPUT_DATASET, "run ${job.runId}", tokens,
        )
        version.exceptionOrNull()?.let { error ->
            if (KaggleClient.isNotFound(error)) {
                // First run on this account: create the dataset instead.
                KaggleClient.createDataset(
                    creds, RvcAssets.INPUT_DATASET, "CloneCast Input Audio", tokens,
                ).getOrThrow()
            } else {
                throw error
            }
        }
    }

    private suspend fun waitDatasetReady(creds: KaggleClient.Creds, job: ConvertJob) {
        val deadline = System.currentTimeMillis() + DATASET_TIMEOUT_MS
        while (true) {
            report(job, ConvertStage.WAITING_DATASET, "Waiting for Kaggle to process the upload…")
            val status = KaggleClient.datasetStatus(creds, RvcAssets.INPUT_DATASET).getOrThrow()
            when {
                status.contains("READY") -> return
                status.contains("FAILED") || status.contains("DELETED") ->
                    throw IllegalStateException("Kaggle could not process the upload ($status) — retry")
            }
            if (System.currentTimeMillis() > deadline) {
                throw IllegalStateException("Upload processing timed out — retry the conversion")
            }
            delay(10_000)
        }
    }

    private suspend fun pushKernel(context: Context, creds: KaggleClient.Creds, job: ConvertJob) {
        // The trained model comes from the training kernel's output; verify it exists.
        if (!isModelReady(creds)) {
            throw IllegalStateException(
                "Voice model not trained yet on '${creds.username}' — use the " +
                    "\"Train voice model\" card first (one-time, ~1 hour).",
            )
        }
        report(job, ConvertStage.PUSHING, "Starting Kaggle T4 converter…")
        val script = RvcAssets.converterScript(context, job.runId, job.inputSha256)
        KaggleClient.pushKernel(
            creds,
            RvcAssets.CONVERT_KERNEL,
            script,
            datasetSources = listOf("${creds.username}/${RvcAssets.INPUT_DATASET}"),
            kernelSources = listOf("${creds.username}/${RvcAssets.TRAIN_KERNEL}"),
        ).getOrThrow()
        KaggleStore.markBootstrapped(context, creds.username)
    }

    // --- Voice-model training (Phase 8.7: driven from the phone) ---

    /** True when the training kernel's output contains a trained model. */
    suspend fun isModelReady(creds: KaggleClient.Creds): Boolean =
        KaggleClient.kernelOutput(creds, RvcAssets.TRAIN_KERNEL)
            .getOrDefault(emptyList())
            .any { it.fileName.endsWith("model.pth") }

    /**
     * Pushes + starts the one-time training run on Kaggle T4.
     * Needs the clonecast-voice-raw dataset on the account (voice audio).
     */
    suspend fun startTraining(context: Context): Result<Unit> = runCatching {
        val creds = credsOrThrow(context)
        val voiceStatus = KaggleClient.datasetStatus(creds, RvcAssets.VOICE_DATASET)
        voiceStatus.exceptionOrNull()?.let { error ->
            if (KaggleClient.isNotFound(error)) {
                throw IllegalStateException(
                    "Voice dataset '${RvcAssets.VOICE_DATASET}' not found on " +
                        "'${creds.username}' — upload your voice audio there first.",
                )
            }
            throw error
        }
        KaggleClient.pushKernel(
            creds,
            RvcAssets.TRAIN_KERNEL,
            RvcAssets.trainingScript(context),
            datasetSources = listOf("${creds.username}/${RvcAssets.VOICE_DATASET}"),
        ).getOrThrow()
    }

    /** Human-readable status of the training kernel for the Voice-model card. */
    suspend fun trainingStatus(context: Context): Result<String> = runCatching {
        val creds = credsOrThrow(context)
        val state = KaggleClient.kernelStatus(creds, RvcAssets.TRAIN_KERNEL).getOrThrow()
        when (state.status) {
            "COMPLETE" ->
                if (isModelReady(creds)) "READY ✓ — voice model trained, you can convert"
                else "Finished but no model in output — check the run on kaggle.com"
            "QUEUED", "NEW_SCRIPT" -> "Waiting for a free Kaggle GPU…"
            "RUNNING" -> "Training on Kaggle T4… (~40-60 min total)"
            "ERROR" -> "Training failed: ${state.failureMessage ?: "see kaggle.com log"}"
            "CANCEL_REQUESTED", "CANCEL_ACKNOWLEDGED" ->
                "Run was canceled — do NOT open kaggle.com while it runs; tap Train again"
            else -> state.status
        }
    }

    private suspend fun pollKernel(context: Context, creds: KaggleClient.Creds, job: ConvertJob): String {
        val deadline = System.currentTimeMillis() + KERNEL_TIMEOUT_MS
        while (true) {
            val state = KaggleClient.kernelStatus(creds, RvcAssets.CONVERT_KERNEL).getOrThrow()
            when (state.status) {
                "COMPLETE" -> return state.status
                "ERROR" -> throw IllegalStateException(
                    "Kaggle run failed: ${state.failureMessage ?: "see kernel log on kaggle.com"}",
                )
                "CANCEL_REQUESTED", "CANCEL_ACKNOWLEDGED" ->
                    throw IllegalStateException("Kaggle run was canceled on the website")
                "QUEUED", "NEW_SCRIPT" ->
                    report(job, ConvertStage.RUNNING, "Waiting for a free Kaggle GPU… (can take a few minutes)")
                else ->
                    report(job, ConvertStage.RUNNING, "Converting on Kaggle T4… (installs + convert, ~10-20 min)")
            }
            if (System.currentTimeMillis() > deadline) {
                throw IllegalStateException("Kaggle run timed out after 2 hours — check kaggle.com")
            }
            delay(POLL_INTERVAL_MS)
        }
    }

    private suspend fun downloadOutput(context: Context, creds: KaggleClient.Creds, job: ConvertJob): File {
        report(job, ConvertStage.DOWNLOADING, "Fetching converted audio…", 0f)
        val files = KaggleClient.kernelOutput(creds, RvcAssets.CONVERT_KERNEL).getOrThrow()

        val resultMeta = files.firstOrNull { it.fileName.endsWith("job_result.json") }
            ?: throw IllegalStateException("job_result.json missing from Kaggle output")
        val resultFile = File(context.cacheDir, "job_result.json")
        KaggleClient.downloadFile(creds, resultMeta.url, resultFile).getOrThrow()
        val result = json.parseToJsonElement(resultFile.readText()).jsonObject
        resultFile.delete()

        val resultRunId = result["run_id"]?.jsonPrimitive?.content
        if (resultRunId != job.runId) {
            throw IllegalStateException(
                "Kaggle output belongs to a different run ($resultRunId) — retry the conversion",
            )
        }
        if (result["status"]?.jsonPrimitive?.content != "ok") {
            val error = result["error"]?.jsonPrimitive?.content ?: "unknown kernel error"
            throw IllegalStateException("Conversion failed on Kaggle: ${error.take(300)}")
        }
        if (result["input_sha256"]?.jsonPrimitive?.content != job.inputSha256) {
            throw IllegalStateException("Kaggle converted a different input file — retry")
        }

        val mp3Meta = files.firstOrNull { it.fileName.endsWith("output.mp3") }
            ?: throw IllegalStateException("output.mp3 missing from Kaggle output")
        val mp3 = File(context.cacheDir, "converted_${job.runId}.mp3")
        KaggleClient.downloadFile(creds, mp3Meta.url, mp3) { f ->
            report(job, ConvertStage.DOWNLOADING, "Downloading converted audio…", f)
        }.getOrThrow()
        if (mp3.length() == 0L) throw IllegalStateException("Downloaded file is empty — retry")

        val outMs = audioDurationMs(mp3)
        if (kotlin.math.abs(outMs - job.inputDurationMs) > 1_000) {
            mp3.delete()
            throw IllegalStateException(
                "Duration check failed (in ${job.inputDurationMs / 1000}s, out ${outMs / 1000}s)",
            )
        }
        return mp3
    }

    private fun safeFileName(title: String): String =
        title.replace(Regex("[^A-Za-z0-9 _-]"), "").trim().ifBlank { "converted" } + ".mp3"

    /** Phase 1 (API 29+): insert an invisible IS_PENDING row; its URI is persisted before writing. */
    private fun createPendingAudio(context: Context, title: String): Uri {
        val values = ContentValues().apply {
            put(MediaStore.Audio.Media.DISPLAY_NAME, safeFileName(title))
            put(MediaStore.Audio.Media.MIME_TYPE, "audio/mpeg")
            put(MediaStore.Audio.Media.RELATIVE_PATH, Environment.DIRECTORY_MUSIC + "/CloneCast")
            put(MediaStore.Audio.Media.IS_PENDING, 1)
        }
        return context.contentResolver.insert(MediaStore.Audio.Media.EXTERNAL_CONTENT_URI, values)
            ?: throw IllegalStateException("Could not create file in Music folder")
    }

    /** Phase 2 (API 29+): write the bytes and flip IS_PENDING off. */
    private fun finalizePendingAudio(context: Context, uri: Uri, mp3: File) {
        val resolver = context.contentResolver
        resolver.openOutputStream(uri).use { out ->
            if (out == null) throw IllegalStateException("Could not open output file")
            mp3.inputStream().use { it.copyTo(out) }
        }
        val values = ContentValues().apply { put(MediaStore.Audio.Media.IS_PENDING, 0) }
        val updated = resolver.update(uri, values, null, null)
        if (updated != 1) {
            // File would stay invisible (still pending) while the job claims DONE.
            throw IllegalStateException("Could not finalize the export — retry the conversion")
        }
    }

    /** Pre-29: per-run path in app-external storage — retry overwrites, runs never collide. */
    private fun saveToMusicLegacy(context: Context, title: String, runId: String, mp3: File): Uri {
        val dir = File(context.getExternalFilesDir(Environment.DIRECTORY_MUSIC), "CloneCast")
            .apply { mkdirs() }
        val base = safeFileName(title).removeSuffix(".mp3")
        val out = File(dir, "$base-${runId.take(8)}.mp3")
        mp3.inputStream().use { input -> out.outputStream().use { input.copyTo(it) } }
        return FileProvider.getUriForFile(context, context.packageName + ".fileprovider", out)
    }

    // --- Helpers ---

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(1 shl 16)
            while (true) {
                val read = input.read(buffer)
                if (read < 0) break
                digest.update(buffer, 0, read)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun audioDurationMs(file: File): Long {
        // MediaMetadataRetriever.close() needs API 29; release() works on minSdk 26.
        val retriever = MediaMetadataRetriever()
        return try {
            retriever.setDataSource(file.absolutePath)
            retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
                ?.toLongOrNull() ?: 0L
        } finally {
            retriever.release()
        }
    }

    private fun audioMime(file: File): String = when (file.extension.lowercase()) {
        "mp3", "mpeg" -> "audio/mpeg"
        "wav" -> "audio/wav"
        "ogg", "opus" -> "audio/ogg"
        "flac" -> "audio/flac"
        else -> "audio/mp4"
    }
}
