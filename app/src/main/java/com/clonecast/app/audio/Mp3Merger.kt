package com.clonecast.app.audio

import java.io.File
import java.io.OutputStream

/** Concatenates MP3 chunk files into one stream, skipping per-file ID3v2 tags. */
object Mp3Merger {
    fun merge(chunks: List<File>, dest: OutputStream) {
        chunks.forEach { file ->
            dest.write(stripId3(file.readBytes()))
        }
        dest.flush()
    }

    private fun stripId3(bytes: ByteArray): ByteArray {
        if (bytes.size > 10 &&
            bytes[0] == 'I'.code.toByte() &&
            bytes[1] == 'D'.code.toByte() &&
            bytes[2] == '3'.code.toByte()
        ) {
            val size = ((bytes[6].toInt() and 0x7F) shl 21) or
                ((bytes[7].toInt() and 0x7F) shl 14) or
                ((bytes[8].toInt() and 0x7F) shl 7) or
                (bytes[9].toInt() and 0x7F)
            val start = 10 + size
            if (start in 1 until bytes.size) {
                return bytes.copyOfRange(start, bytes.size)
            }
        }
        return bytes
    }
}
