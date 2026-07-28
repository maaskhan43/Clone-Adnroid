package com.clonecast.app.convert

import android.content.Context

/**
 * Loads the converter kernel script from app assets and fills in the per-run
 * placeholders. The script file (assets/rvc_convert_kernel.py) is the single
 * source of truth — Gate 0 dry-runs push the same file manually.
 */
object RvcAssets {
    const val MODEL_DATASET = "clonecast-rvc-model"
    const val INPUT_DATASET = "clonecast-input-audio"
    const val CONVERT_KERNEL = "clonecast-rvc-convert"

    /**
     * RVC commit the converter is pinned to. This is the commit whose inference
     * API (configs.config.Config + infer.vc.modules.VC) the script was written
     * against. Gate 0 dry-run re-confirms it; update only after a passing dry-run.
     */
    const val RVC_COMMIT = "4338f12c3c28c80b3ac015e2d0df66c41592746d"

    fun converterScript(context: Context, runId: String, inputSha256: String): String =
        context.assets.open("rvc_convert_kernel.py").bufferedReader().use { it.readText() }
            .replace("__RUN_ID__", runId)
            .replace("__RVC_COMMIT__", RVC_COMMIT)
            .replace("__INPUT_SHA256__", inputSha256)

    fun jobJson(runId: String, inputSha256: String, durationMs: Long, fileName: String): String =
        """{"run_id":"$runId","input_sha256":"$inputSha256","duration_ms":$durationMs,"file_name":"$fileName"}"""
}
