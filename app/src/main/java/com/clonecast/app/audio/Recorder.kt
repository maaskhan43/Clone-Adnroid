package com.clonecast.app.audio

import android.content.Context
import android.media.MediaMetadataRetriever
import android.media.MediaPlayer
import android.media.MediaRecorder
import android.os.Build
import java.io.File

/** Duration of an audio file in whole seconds, or 0 if unreadable. */
fun audioDurationSec(path: String): Int = runCatching {
    val retriever = MediaMetadataRetriever()
    retriever.setDataSource(path)
    val ms = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
        ?.toLongOrNull() ?: 0L
    retriever.release()
    (ms / 1000L).toInt()
}.getOrDefault(0)

/** Records mic audio to an AAC .m4a file under filesDir/samples/. */
class SampleRecorder(private val context: Context) {
    private var recorder: MediaRecorder? = null
    var outputFile: File? = null
        private set

    val isRecording: Boolean get() = recorder != null

    fun start(fileBaseName: String): File {
        val dir = File(context.filesDir, "samples").apply { mkdirs() }
        // Record to a temp file so a failed take never destroys the existing sample.
        val file = File(dir, "$fileBaseName.rec.m4a")
        if (file.exists()) file.delete()

        val r =
            if (Build.VERSION.SDK_INT >= 31) MediaRecorder(context)
            else @Suppress("DEPRECATION") MediaRecorder()
        r.setAudioSource(MediaRecorder.AudioSource.MIC)
        r.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
        r.setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
        r.setAudioSamplingRate(44100)
        r.setAudioEncodingBitRate(128_000)
        r.setAudioChannels(1)
        r.setOutputFile(file.absolutePath)
        r.prepare()
        r.start()

        recorder = r
        outputFile = file
        return file
    }

    /** 0..32767 — current input level while recording. */
    val maxAmplitude: Int get() = runCatching { recorder?.maxAmplitude ?: 0 }.getOrDefault(0)

    /** Returns the recorded file, or null if recording failed (bad file is deleted). */
    fun stop(): File? {
        val file = outputFile
        val stopped = runCatching { recorder?.stop() }.isSuccess
        recorder?.release()
        recorder = null
        // MediaRecorder.stop() throws if nothing was captured; a tiny file is also unusable.
        val valid = stopped && file != null && file.exists() && file.length() > 4096
        if (!valid) {
            file?.delete()
            outputFile = null
            return null
        }
        val final = File(file!!.parentFile, file.name.removeSuffix(".rec.m4a") + ".m4a")
        if (final.exists()) final.delete()
        return if (file.renameTo(final)) final else file
    }
}

/** Simple playback for recorded samples. */
class SamplePlayer {
    private var player: MediaPlayer? = null

    /** Current playback position in ms (0 when not playing). */
    val positionMs: Int
        get() = runCatching { player?.currentPosition ?: 0 }.getOrDefault(0)

    fun play(path: String, onComplete: () -> Unit) {
        stop()
        player = MediaPlayer().apply {
            setDataSource(path)
            prepare()
            setOnCompletionListener {
                stopInternal()
                onComplete()
            }
            start()
        }
    }

    fun stop() = stopInternal()

    private fun stopInternal() {
        runCatching { player?.stop() }
        runCatching { player?.release() }
        player = null
    }
}
