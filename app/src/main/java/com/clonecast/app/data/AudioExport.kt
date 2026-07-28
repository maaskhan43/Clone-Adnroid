package com.clonecast.app.data

import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import androidx.core.content.FileProvider
import com.clonecast.app.audio.Mp3Merger
import java.io.File
import java.io.FileOutputStream

object AudioExport {

    /** Merges chunk MP3s and saves to Music/CloneCast (API 29+) or app storage (older). */
    fun exportToMusic(context: Context, title: String, chunkFiles: List<File>): Uri {
        val safeName = title.replace(Regex("[^A-Za-z0-9 _-]"), "").trim().ifBlank { "narration" }
        val fileName = "$safeName.mp3"

        return if (Build.VERSION.SDK_INT >= 29) {
            val values = ContentValues().apply {
                put(MediaStore.Audio.Media.DISPLAY_NAME, fileName)
                put(MediaStore.Audio.Media.MIME_TYPE, "audio/mpeg")
                put(MediaStore.Audio.Media.RELATIVE_PATH, Environment.DIRECTORY_MUSIC + "/CloneCast")
                put(MediaStore.Audio.Media.IS_PENDING, 1)
            }
            val resolver = context.contentResolver
            val uri = resolver.insert(MediaStore.Audio.Media.EXTERNAL_CONTENT_URI, values)
                ?: throw IllegalStateException("Could not create file in Music folder")
            resolver.openOutputStream(uri).use { out ->
                if (out == null) throw IllegalStateException("Could not open output file")
                Mp3Merger.merge(chunkFiles, out)
            }
            values.clear()
            values.put(MediaStore.Audio.Media.IS_PENDING, 0)
            resolver.update(uri, values, null, null)
            uri
        } else {
            val dir = File(context.getExternalFilesDir(Environment.DIRECTORY_MUSIC), "CloneCast")
                .apply { mkdirs() }
            val out = File(dir, fileName)
            FileOutputStream(out).use { Mp3Merger.merge(chunkFiles, it) }
            FileProvider.getUriForFile(context, context.packageName + ".fileprovider", out)
        }
    }

    fun share(context: Context, uri: Uri) {
        val intent = Intent(Intent.ACTION_SEND).apply {
            type = "audio/mpeg"
            putExtra(Intent.EXTRA_STREAM, uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        context.startActivity(Intent.createChooser(intent, "Share narration"))
    }
}
