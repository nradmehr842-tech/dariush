from pathlib import Path
import re
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else 'upstream').resolve()
app = root / 'V2rayNG' / 'app'
src = app / 'src' / 'main'
java = src / 'java' / 'com' / 'v2ray' / 'ang'
res = src / 'res'

def read(p):
    return p.read_text(encoding='utf-8')

def write(p, s):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding='utf-8')

def replace_once(p, old, new, label):
    s = read(p)
    if old not in s:
        raise SystemExit(f'PATCH FAILED: {label} not found in {p}')
    write(p, s.replace(old, new, 1))

# ---- Brand / package ----
gradle = app / 'build.gradle.kts'
s = read(gradle)
s = s.replace('applicationId = "com.v2ray.ang"', 'applicationId = "com.mediatelecom.onetapvpn"', 1)
s = s.replace('applicationIdSuffix = ".fdroid"', '// OneTapVPN: no applicationIdSuffix', 1)
s = s.replace('versionName = "2.2.6"', 'versionName = "1.0.0"', 1)
s = s.replace('"v2rayNG_${variant.versionName}-fdroid_${abi}.apk"', '"OneTapVPN_${variant.versionName}_${abi}.apk"', 1)
write(gradle, s)

strings = res / 'values' / 'strings.xml'
replace_once(strings,
             '<string name="app_name" translatable="false">v2rayNG</string>',
             '<string name="app_name" translatable="false">داریوش</string>',
             'app name')

# ---- One-tap transparent activity ----
one_tap = r'''package com.v2ray.ang.ui

import android.app.AlertDialog
import android.content.Intent
import android.net.VpnService
import android.os.Bundle
import android.text.InputType
import android.view.ViewGroup
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.Toast
import androidx.lifecycle.lifecycleScope
import com.v2ray.ang.AppConfig
import com.v2ray.ang.handler.AngConfigManager
import com.v2ray.ang.handler.MmkvManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * First run: asks once for a v2rayNG-compatible share/subscription URL and VPN consent.
 * Later runs: stays transparent, forwards the tap to ScSwitchActivity, then exits.
 */
class OneTapActivity : BaseActivity() {

    companion object {
        private const val PREFS = "onetap_setup"
        private const val KEY_IMPORTED = "imported"
        private const val KEY_READY = "ready"
        private const val VPN_REQUEST = 8112
    }

    private val prefs by lazy { getSharedPreferences(PREFS, MODE_PRIVATE) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        if (prefs.getBoolean(KEY_READY, false)) {
            toggleAndClose()
            return
        }

        if (prefs.getBoolean(KEY_IMPORTED, false)) {
            requestVpnPermissionOrFinishSetup()
            return
        }

        showLinkDialog()
    }

    private fun showLinkDialog() {
        val input = EditText(this).apply {
            hint = "vless://...  یا لینک اشتراک"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            isSingleLine = false
            layoutDirection = android.view.View.LAYOUT_DIRECTION_LTR
            setPadding(36, 24, 36, 24)
        }
        val holder = FrameLayout(this).apply {
            val lp = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            ).apply { setMargins(24, 8, 24, 0) }
            addView(input, lp)
        }

        val dialog = AlertDialog.Builder(this)
            .setTitle("لینک اتصال")
            .setMessage("لینکی را وارد کنید که در v2rayNG کار می‌کند. این مرحله فقط یک‌بار نمایش داده می‌شود.")
            .setView(holder)
            .setCancelable(false)
            .setNegativeButton("خروج") { _, _ -> finishAndRemoveTask() }
            .setPositiveButton("ثبت", null)
            .create()

        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                val link = input.text?.toString()?.trim().orEmpty()
                if (link.isBlank()) {
                    input.error = "لینک را وارد کنید"
                    return@setOnClickListener
                }
                dialog.getButton(AlertDialog.BUTTON_POSITIVE).isEnabled = false
                input.isEnabled = false
                importLink(link, dialog, input)
            }
        }
        dialog.setOnDismissListener {
            if (!prefs.getBoolean(KEY_READY, false) && !isFinishing) {
                // Keep first-run behavior deterministic if the dialog is dismissed unexpectedly.
                finishAndRemoveTask()
            }
        }
        dialog.show()
    }

    private fun importLink(link: String, dialog: AlertDialog, input: EditText) {
        lifecycleScope.launch(Dispatchers.IO) {
            val result = runCatching {
                AngConfigManager.importBatchConfig(link, AppConfig.DEFAULT_SUBSCRIPTION_ID, true)
            }
            val imported = result.getOrNull()?.let { it.first + it.second } ?: 0

            // Import does not always select a profile on a fresh install; choose the first available one.
            if (imported > 0 && MmkvManager.getSelectServer().isNullOrBlank()) {
                MmkvManager.decodeAllServerList().firstOrNull()?.let(MmkvManager::setSelectServer)
            }
            val usable = imported > 0 && !MmkvManager.getSelectServer().isNullOrBlank()

            withContext(Dispatchers.Main) {
                if (!usable) {
                    dialog.getButton(AlertDialog.BUTTON_POSITIVE).isEnabled = true
                    input.isEnabled = true
                    Toast.makeText(this@OneTapActivity, "لینک معتبر نیست یا کانفیگی دریافت نشد", Toast.LENGTH_LONG).show()
                    return@withContext
                }
                prefs.edit().putBoolean(KEY_IMPORTED, true).apply()
                dialog.setOnDismissListener(null)
                dialog.dismiss()
                requestVpnPermissionOrFinishSetup()
            }
        }
    }

    private fun requestVpnPermissionOrFinishSetup() {
        val intent = VpnService.prepare(this)
        if (intent == null) {
            markReadyAndClose()
        } else {
            startActivityForResult(intent, VPN_REQUEST)
        }
    }

    @Deprecated("Deprecated in Android API; kept for compatibility with v2rayNG minSdk")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == VPN_REQUEST) {
            if (resultCode == RESULT_OK) {
                markReadyAndClose()
            } else {
                Toast.makeText(this, "برای اتصال، مجوز VPN لازم است", Toast.LENGTH_LONG).show()
                finishAndRemoveTask()
            }
        }
    }

    private fun markReadyAndClose() {
        prefs.edit().putBoolean(KEY_READY, true).apply()
        finishAndRemoveTask()
    }

    private fun toggleAndClose() {
        // ScSwitchActivity runs in the same process as the Xray service, so its isRunning() is authoritative.
        startActivity(Intent(this, ScSwitchActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NO_ANIMATION))
        overridePendingTransition(0, 0)
        finishAndRemoveTask()
    }
}
'''
write(java / 'ui' / 'OneTapActivity.kt', one_tap)

# ---- Launcher icon state manager ----
icon_mgr = r'''package com.v2ray.ang.handler

import android.content.ComponentName
import android.content.Context
import android.content.pm.PackageManager
import com.v2ray.ang.BuildConfig

object LauncherIconManager {
    private fun white(context: Context) = ComponentName(context, "${BuildConfig.APPLICATION_ID}.LauncherWhite")
    private fun green(context: Context) = ComponentName(context, "${BuildConfig.APPLICATION_ID}.LauncherGreen")

    @Synchronized
    fun setConnected(context: Context, connected: Boolean) {
        val pm = context.packageManager
        val enable = if (connected) green(context) else white(context)
        val disable = if (connected) white(context) else green(context)

        // Enable the new launcher alias first to avoid a moment with no launcher entry.
        pm.setComponentEnabledSetting(
            enable,
            PackageManager.COMPONENT_ENABLED_STATE_ENABLED,
            PackageManager.DONT_KILL_APP
        )
        pm.setComponentEnabledSetting(
            disable,
            PackageManager.COMPONENT_ENABLED_STATE_DISABLED,
            PackageManager.DONT_KILL_APP
        )
    }
}
'''
write(java / 'handler' / 'LauncherIconManager.kt', icon_mgr)

# ---- Accurate icon synchronization with real Xray core state ----
core = java / 'core' / 'CoreServiceManager.kt'
s = read(core)
if 'import com.v2ray.ang.handler.LauncherIconManager' not in s:
    s = s.replace('import com.v2ray.ang.handler.MmkvManager\n', 'import com.v2ray.ang.handler.MmkvManager\nimport com.v2ray.ang.handler.LauncherIconManager\n', 1)
s = s.replace(
    'MessageUtil.sendMsg2UI(service, AppConfig.MSG_STATE_START_FAILURE, message)\n            NotificationManager.cancelNotification()',
    'MessageUtil.sendMsg2UI(service, AppConfig.MSG_STATE_START_FAILURE, message)\n            LauncherIconManager.setConnected(service, false)\n            NotificationManager.cancelNotification()',
    1
)
s = s.replace(
    'LogUtil.i(AppConfig.TAG, "StartCore-Manager: Core started successfully")',
    'LauncherIconManager.setConnected(service, true)\n        LogUtil.i(AppConfig.TAG, "StartCore-Manager: Core started successfully")',
    1
)
s = s.replace(
    'MessageUtil.sendMsg2UI(service, AppConfig.MSG_STATE_STOP_SUCCESS, "")\n        NotificationManager.cancelNotification()',
    'MessageUtil.sendMsg2UI(service, AppConfig.MSG_STATE_STOP_SUCCESS, "")\n        LauncherIconManager.setConnected(service, false)\n        NotificationManager.cancelNotification()',
    1
)
write(core, s)

vpn = java / 'service' / 'CoreVpnService.kt'
s = read(vpn)
if 'import com.v2ray.ang.handler.LauncherIconManager' not in s:
    s = s.replace('import com.v2ray.ang.handler.MmkvManager\n', 'import com.v2ray.ang.handler.MmkvManager\nimport com.v2ray.ang.handler.LauncherIconManager\n', 1)
s = s.replace(
    'NotificationManager.cancelNotification()\n    }\n\n    override fun onStartCommand',
    'LauncherIconManager.setConnected(this, false)\n        NotificationManager.cancelNotification()\n    }\n\n    override fun onStartCommand',
    1
)
write(vpn, s)

# ---- Manifest: hide normal UI launcher; expose only two state aliases ----
manifest = src / 'AndroidManifest.xml'
s = read(manifest)
old_main = '''        <activity
            android:name=".ui.MainActivity"
            android:exported="true"
            android:launchMode="singleTask">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
                <category android:name="android.intent.category.LEANBACK_LAUNCHER" />
            </intent-filter>
            <intent-filter>
                <action android:name="android.service.quicksettings.action.QS_TILE_PREFERENCES" />
            </intent-filter>
            <meta-data
                android:name="android.app.shortcuts"
                android:resource="@xml/shortcuts" />
        </activity>'''
new_main = '''        <activity
            android:name=".ui.MainActivity"
            android:exported="true"
            android:launchMode="singleTask">
            <intent-filter>
                <action android:name="android.service.quicksettings.action.QS_TILE_PREFERENCES" />
            </intent-filter>
            <meta-data
                android:name="android.app.shortcuts"
                android:resource="@xml/shortcuts" />
        </activity>

        <activity
            android:name=".ui.OneTapActivity"
            android:excludeFromRecents="true"
            android:exported="true"
            android:launchMode="singleTop"
            android:theme="@style/OneTapTransparentTheme" />

        <activity-alias
            android:name="${applicationId}.LauncherWhite"
            android:enabled="true"
            android:exported="true"
            android:icon="@drawable/ic_onetap_white"
            android:label="@string/app_name"
            android:targetActivity=".ui.OneTapActivity">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity-alias>

        <activity-alias
            android:name="${applicationId}.LauncherGreen"
            android:enabled="false"
            android:exported="true"
            android:icon="@drawable/ic_onetap_green"
            android:label="@string/app_name"
            android:targetActivity=".ui.OneTapActivity">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity-alias>'''
if old_main not in s:
    raise SystemExit('PATCH FAILED: MainActivity manifest block not found')
s = s.replace(old_main, new_main, 1)
write(manifest, s)

# ---- Transparent window style ----
style = '''<?xml version="1.0" encoding="utf-8"?>
<resources>
    <style name="OneTapTransparentTheme" parent="Theme.AppCompat.DayNight.NoActionBar">
        <item name="android:windowIsTranslucent">true</item>
        <item name="android:windowBackground">@android:color/transparent</item>
        <item name="android:windowNoTitle">true</item>
        <item name="android:backgroundDimEnabled">false</item>
        <item name="android:windowDisablePreview">true</item>
        <item name="android:colorAccent">#2DBE60</item>
    </style>
</resources>
'''
write(res / 'values' / 'onetap_styles.xml', style)

# ---- Glassy white/green circle icons ----
white_icon = '''<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="108dp" android:height="108dp" android:viewportWidth="108" android:viewportHeight="108">
    <!-- soft shadow behind the glass orb -->
    <path android:fillColor="#26000000" android:pathData="M54,8a46,46 0,1 0,0 92a46,46 0,1 0,0 -92"/>
    <!-- translucent frosted-glass body -->
    <path android:fillColor="#B8FFFFFF" android:strokeColor="#F2FFFFFF" android:strokeWidth="2.4"
        android:pathData="M54,13a41,41 0,1 0,0 82a41,41 0,1 0,0 -82"/>
    <!-- inner glass rim -->
    <path android:fillColor="#00FFFFFF" android:strokeColor="#66FFFFFF" android:strokeWidth="1.3"
        android:pathData="M54,18a36,36 0,1 0,0 72a36,36 0,1 0,0 -72"/>
    <!-- glossy highlight -->
    <path android:fillColor="#72FFFFFF" android:pathData="M28,32C36,19 53,14 70,19C54,20 40,27 29,39C26,37 26,35 28,32Z"/>
    <!-- subtle lower reflection -->
    <path android:fillColor="#28FFFFFF" android:pathData="M34,76C45,84 64,84 75,75C67,88 42,91 31,79Z"/>
</vector>
'''
green_icon = '''<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="108dp" android:height="108dp" android:viewportWidth="108" android:viewportHeight="108">
    <!-- soft shadow behind the glass orb -->
    <path android:fillColor="#26000000" android:pathData="M54,8a46,46 0,1 0,0 92a46,46 0,1 0,0 -92"/>
    <!-- translucent connected-state glass body -->
    <path android:fillColor="#D92DBE60" android:strokeColor="#F2FFFFFF" android:strokeWidth="2.4"
        android:pathData="M54,13a41,41 0,1 0,0 82a41,41 0,1 0,0 -82"/>
    <!-- inner glass rim -->
    <path android:fillColor="#00FFFFFF" android:strokeColor="#62FFFFFF" android:strokeWidth="1.3"
        android:pathData="M54,18a36,36 0,1 0,0 72a36,36 0,1 0,0 -72"/>
    <!-- glossy highlight -->
    <path android:fillColor="#66FFFFFF" android:pathData="M28,32C36,19 53,14 70,19C54,20 40,27 29,39C26,37 26,35 28,32Z"/>
    <!-- subtle lower reflection -->
    <path android:fillColor="#24FFFFFF" android:pathData="M34,76C45,84 64,84 75,75C67,88 42,91 31,79Z"/>
</vector>
'''
write(res / 'drawable' / 'ic_onetap_white.xml', white_icon)
write(res / 'drawable' / 'ic_onetap_green.xml', green_icon)

print('OneTapVPN patch applied successfully')
