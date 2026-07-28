package com.clonecast.app.data

import android.content.ContentValues
import android.content.Context
import android.graphics.Bitmap
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import androidx.core.content.FileProvider
import java.io.File
import java.io.FileOutputStream

object VideoExport {

    /** Saves an exported part into Movies/CloneCast/[folder]/ (gallery-visible on API 29+). */
    fun saveVideoToMovies(context: Context, folder: String, fileName: String, src: File): Uri {
        return if (Build.VERSION.SDK_INT >= 29) {
            val values = ContentValues().apply {
                put(MediaStore.Video.Media.DISPLAY_NAME, fileName)
                put(MediaStore.Video.Media.MIME_TYPE, "video/mp4")
                put(
                    MediaStore.Video.Media.RELATIVE_PATH,
                    Environment.DIRECTORY_MOVIES + "/CloneCast/" + folder,
                )
                put(MediaStore.Video.Media.IS_PENDING, 1)
            }
            val resolver = context.contentResolver
            val uri = resolver.insert(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, values)
                ?: throw IllegalStateException("Could not create file in Movies")
            resolver.openOutputStream(uri).use { out ->
                if (out == null) throw IllegalStateException("Could not open output file")
                src.inputStream().use { it.copyTo(out) }
            }
            values.clear()
            values.put(MediaStore.Video.Media.IS_PENDING, 0)
            resolver.update(uri, values, null, null)
            uri
        } else {
            val dir = File(
                context.getExternalFilesDir(Environment.DIRECTORY_MOVIES),
                "CloneCast/$folder",
            ).apply { mkdirs() }
            val out = File(dir, fileName)
            src.copyTo(out, overwrite = true)
            FileProvider.getUriForFile(context, context.packageName + ".fileprovider", out)
        }
    }

    /** Saves a part thumbnail into Pictures/CloneCast/[folder]/. */
    fun saveThumbnail(context: Context, folder: String, fileName: String, bitmap: Bitmap) {
        if (Build.VERSION.SDK_INT >= 29) {
            val values = ContentValues().apply {
                put(MediaStore.Images.Media.DISPLAY_NAME, fileName)
                put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg")
                put(
                    MediaStore.Images.Media.RELATIVE_PATH,
                    Environment.DIRECTORY_PICTURES + "/CloneCast/" + folder,
                )
            }
            val resolver = context.contentResolver
            val uri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
                ?: return
            resolver.openOutputStream(uri)?.use { out ->
                bitmap.compress(Bitmap.CompressFormat.JPEG, 85, out)
            }
        } else {
            val dir = File(
                context.getExternalFilesDir(Environment.DIRECTORY_PICTURES),
                "CloneCast/$folder",
            ).apply { mkdirs() }
            FileOutputStream(File(dir, fileName)).use { out ->
                bitmap.compress(Bitmap.CompressFormat.JPEG, 85, out)
            }
        }
    }
}
