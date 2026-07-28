package com.clonecast.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Face
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.clonecast.app.ui.CloneCastTheme
import com.clonecast.app.ui.ColabScreen
import com.clonecast.app.ui.ConvertScreen
import com.clonecast.app.ui.DubScreen
import com.clonecast.app.ui.GenerateScreen
import com.clonecast.app.ui.ProfilesScreen
import com.clonecast.app.ui.RecordScreen
import com.clonecast.app.ui.SettingsScreen
import com.clonecast.app.ui.SplitScreen

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            CloneCastTheme {
                AppRoot()
            }
        }
    }
}

private data class Destination(
    val route: String,
    val label: String,
    val icon: ImageVector,
)

private val destinations = listOf(
    Destination("profiles", "Profiles", Icons.Filled.Person),
    Destination("generate", "Generate", Icons.Filled.PlayArrow),
    Destination("split", "Reels", Icons.Filled.Share),
    Destination("dub", "Dub", Icons.Filled.Face),
    Destination("convert", "Convert", Icons.Filled.Refresh),
    Destination("colab", "Colab", Icons.Filled.Star),
    Destination("settings", "Settings", Icons.Filled.Settings),
)

@Composable
fun AppRoot() {
    val nav = rememberNavController()
    Scaffold(
        bottomBar = {
            NavigationBar {
                val backStack by nav.currentBackStackEntryAsState()
                val currentRoute = backStack?.destination?.route
                destinations.forEach { dest ->
                    NavigationBarItem(
                        selected = currentRoute == dest.route,
                        onClick = {
                            nav.navigate(dest.route) {
                                popUpTo(nav.graph.startDestinationId) { saveState = true }
                                launchSingleTop = true
                                restoreState = true
                            }
                        },
                        icon = { Icon(dest.icon, contentDescription = dest.label) },
                        label = { Text(dest.label) },
                    )
                }
            }
        },
    ) { padding ->
        NavHost(
            navController = nav,
            startDestination = "profiles",
            modifier = Modifier.padding(padding),
        ) {
            composable("profiles") {
                ProfilesScreen(onRecord = { id -> nav.navigate("record/$id") })
            }
            composable("record/{profileId}") { backStackEntry ->
                RecordScreen(
                    profileId = backStackEntry.arguments?.getString("profileId").orEmpty(),
                    onBack = { nav.popBackStack() },
                )
            }
            composable("generate") { GenerateScreen() }
            composable("split") { SplitScreen() }
            composable("dub") { DubScreen() }
            composable("convert") { ConvertScreen() }
            composable("colab") { ColabScreen() }
            composable("settings") { SettingsScreen() }
        }
    }
}
