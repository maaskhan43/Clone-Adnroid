package com.clonecast.app.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val CloneCastColors = darkColorScheme(
    primary = Color(0xFF7C6CF0),
    secondary = Color(0xFF4FC3F7),
    background = Color(0xFF121220),
    surface = Color(0xFF1A1B2E),
    surfaceVariant = Color(0xFF23243A),
    onPrimary = Color.White,
    onBackground = Color(0xFFE6E6F0),
    onSurface = Color(0xFFE6E6F0),
    onSurfaceVariant = Color(0xFFB9BAD1),
    error = Color(0xFFFF6B6B),
)

@Composable
fun CloneCastTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = CloneCastColors, content = content)
}
