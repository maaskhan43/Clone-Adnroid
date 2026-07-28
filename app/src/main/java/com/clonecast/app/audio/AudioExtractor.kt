package com.clonecast.app.audio

import android.content.Context
import android.net.Uri
import androidx.annotation.OptIn
import androidx.media3.common.MediaItem
import androidx.media3.common.util.UnstableApi
import androidx.media3.transformer.Composition
import androidx.media3.transformer.EditedMediaItem
import androidx.media3.transformer.ExportException
import androidx.media3.transformer.ExportResult
import androidx.media3.transformer.Transformer
import kotlinx.coroutines.suspendCancellableCoroutine
import java.io.File
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/** Pulls the audio track out of a video into an .m4a file (no re-encode of audio). */
object AudioExtractor {

    /** Must be called from the main thread (Transformer requirement). */
    @OptIn(UnstableApi::class)
    suspend fun extractToM4a(context: Context, input: Uri, outFile: File) {
        val edited = EditedMediaItem.Builder(MediaItem.fromUri(input))
            .setRemoveVideo(true)
            .build()
        suspendCancellableCoroutine { cont ->
            val transformer = Transformer.Builder(context)
                .addListener(object : Transformer.Listener {
                    override fun onCompleted(composition: Composition, exportResult: ExportResult) {
                        if (cont.isActive) cont.resume(Unit)
                    }

                    override fun onError(
                        composition: Composition,
                        exportResult: ExportResult,
                        exportException: ExportException,
                    ) {
                        if (cont.isActive) cont.resumeWithException(exportException)
                    }
                })
                .build()
            transformer.start(edited, outFile.absolutePath)
            cont.invokeOnCancellation { transformer.cancel() }
        }
    }
}
