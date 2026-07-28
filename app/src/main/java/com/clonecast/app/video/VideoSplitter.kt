package com.clonecast.app.video

import android.content.Context
import android.graphics.Bitmap
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.text.SpannableString
import android.text.Spanned
import android.text.style.AbsoluteSizeSpan
import android.text.style.BackgroundColorSpan
import android.text.style.ForegroundColorSpan
import androidx.annotation.OptIn
import androidx.media3.common.Effect
import androidx.media3.common.MediaItem
import androidx.media3.common.util.UnstableApi
import androidx.media3.effect.OverlayEffect
import androidx.media3.effect.Presentation
import androidx.media3.effect.TextOverlay
import androidx.media3.effect.TextureOverlay
import androidx.media3.transformer.Composition
import androidx.media3.transformer.EditedMediaItem
import androidx.media3.transformer.Effects
import androidx.media3.transformer.ExportException
import androidx.media3.transformer.ExportResult
import androidx.media3.transformer.Transformer
import com.google.common.collect.ImmutableList
import kotlinx.coroutines.suspendCancellableCoroutine
import java.io.File
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/** Cuts a long video into Reel-sized parts with burned-in Part N/M overlays. */
object VideoSplitter {

    const val RECAP_OVERLAP_MS = 2_000L
    private const val INTRO_SHOW_MS = 3_000L
    private const val OUTRO_SHOW_MS = 3_000L

    fun durationMs(context: Context, uri: Uri): Long {
        val retriever = MediaMetadataRetriever()
        return try {
            retriever.setDataSource(context, uri)
            retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
                ?.toLongOrNull() ?: 0L
        } finally {
            runCatching { retriever.release() }
        }
    }

    fun thumbnailAt(context: Context, uri: Uri, timeMs: Long): Bitmap? {
        val retriever = MediaMetadataRetriever()
        return try {
            retriever.setDataSource(context, uri)
            retriever.getFrameAtTime(
                timeMs * 1000,
                MediaMetadataRetriever.OPTION_CLOSEST_SYNC,
            )
        } catch (_: Exception) {
            null
        } finally {
            runCatching { retriever.release() }
        }
    }

    /**
     * Exports one part: clip [startMs, endMs), optional 9:16 reel canvas, and
     * timed overlays (intro "continues from", outro "next part", always Part N/M).
     * Must be called from the main thread (Transformer requirement).
     */
    @OptIn(UnstableApi::class)
    suspend fun exportPart(
        context: Context,
        input: Uri,
        outFile: File,
        startMs: Long,
        endMs: Long,
        partNumber: Int,
        totalParts: Int,
        reel: Boolean,
    ) {
        val mediaItem = MediaItem.Builder()
            .setUri(input)
            .setClippingConfiguration(
                MediaItem.ClippingConfiguration.Builder()
                    .setStartPositionMs(startMs)
                    .setEndPositionMs(endMs)
                    .build(),
            )
            .build()

        val videoEffects = mutableListOf<Effect>()
        if (reel) {
            videoEffects +=
                Presentation.createForWidthAndHeight(1080, 1920, Presentation.LAYOUT_SCALE_TO_FIT)
        }
        videoEffects += OverlayEffect(
            ImmutableList.of<TextureOverlay>(
                partOverlay(partNumber, totalParts, endMs - startMs),
            ),
        )

        val edited = EditedMediaItem.Builder(mediaItem)
            .setEffects(Effects(emptyList(), videoEffects))
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

    @OptIn(UnstableApi::class)
    private fun partOverlay(partNumber: Int, totalParts: Int, partDurationMs: Long): TextOverlay {
        val badge = "Part $partNumber/$totalParts"
        val intro =
            if (partNumber == 1) styled("▶ $badge — start here")
            else styled("▶ $badge\nContinues from Part ${partNumber - 1}")
        val outro =
            if (partNumber < totalParts) styled("Next ➜ Part ${partNumber + 1}")
            else styled("■ The End — $badge")
        val idle = styled(badge, small = true)

        return object : TextOverlay() {
            override fun getText(presentationTimeUs: Long): SpannableString {
                val tMs = presentationTimeUs / 1000
                return when {
                    tMs < INTRO_SHOW_MS -> intro
                    tMs > partDurationMs - OUTRO_SHOW_MS -> outro
                    else -> idle
                }
            }
        }
    }

    private fun styled(text: String, small: Boolean = false): SpannableString =
        SpannableString(text).apply {
            setSpan(
                ForegroundColorSpan(0xFFFFFFFF.toInt()),
                0, length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE,
            )
            setSpan(
                BackgroundColorSpan(0xB0000000.toInt()),
                0, length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE,
            )
            setSpan(
                AbsoluteSizeSpan(if (small) 36 else 64),
                0, length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE,
            )
        }
}
