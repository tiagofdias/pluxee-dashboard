# Pluxee Personal for Android

Native Kotlin / Jetpack Compose companion to the web dashboard. Android 8.0+ (API 26). It calls the Pluxee mobile API directly and needs no cloud database, dashboard server, or paid service.

## Features

- Email/password login, personal name, current balance, transaction history, search and payment/credit filters.
- Six-month spending comparison, top merchants and CSV export through Android's document picker.
- Fictional demo that makes no API calls.
- Optional strong biometric unlock using a cryptographically bound Android Keystore key.
- Optional local transaction notifications using WorkManager. Initial synchronization is silent; later settlement/balance changes do not generate a second alert. Identical genuine purchases are tracked by occurrence.

## Notification limits

Android's minimum periodic WorkManager interval is 15 minutes. Doze, battery restrictions, connectivity and manufacturer policies can delay work. This is polling, not instant push. Force-stopping the application prevents background checks until it is opened again. Only transactions returned by Pluxee can be detected; the API currently requests its latest 100 movements. Older historical backfills are merged without alerts. Session expiration pauses monitoring and asks the user to log in again; passwords are never retained or retried automatically.

Enable **Definições → Novos movimentos** after logging in. Android 13+ also asks for notification permission. Notification details are hidden by default and can be enabled separately. Channels may also be disabled in Android settings.

## Local data and biometrics

Passwords remain in memory only during login and go directly to Pluxee over HTTPS. No analytics, ads, capture logging or cloud database is included. Session records and history are AES-GCM encrypted under Android Keystore keys, in app-private storage, with backup disabled. Screenshots and screen previews are protected with `FLAG_SECURE`. Exporting CSV deliberately creates a user-selected unencrypted file.

Biometric unlock requires a strong enrolled biometric and authenticates an AES-GCM operation through `BiometricPrompt.CryptoObject`. The foreground session key requires authentication for each use and is invalidated by biometric enrollment changes. The app locks when it leaves the foreground. Biometrics unlock an existing Pluxee session; they cannot renew an expired session.

Unattended monitoring necessarily needs access without a biometric prompt. Its separate, optional session grant is encrypted by a non-auth-bound Keystore key. The app explains this before enabling notifications. Disabling notifications deletes that grant. Signing out cancels work, clears notifications, deletes local session/history and invalidates the biometric key. The deduplication ledger is also encrypted locally. A modified/rooted device is outside this protection model.

The Pluxee wire-format compatibility key is a protocol constant from the official application, not a personal credential. TLS and Android Keystore provide the transport/local protection. The upstream protocol is unofficial and may change. Currently one meal card per account is supported; multiple meal cards produce a clear message instead of selecting the wrong one.

## Build

Install JDK 17+ and Android SDK platform 35 / build tools 35.0.0. Set `ANDROID_HOME` or an untracked `local.properties` with `sdk.dir=...`.

```powershell
cd android
.\gradlew.bat testDebugUnitTest assembleDebug lintDebug
```

The installable development APK is `app/build/outputs/apk/debug/app-debug.apk`. Install on a connected device using `adb install -r <apk>`, or transfer the APK and allow installation from the chosen file/browser app. It is signed with the local development key; store publication requires a private release signing key and Play requirements review. Signing material and builds must never be committed.

JVM tests cover the official encryption vector, fresh IVs, deduplication and settlement updates, same-day repeated purchases, rejected transactions/backfills, spending and CSV safety. Physical biometric hardware, upstream live authentication and actual background delivery require device validation.

Reference: [Android biometric authentication](https://developer.android.com/identity/sign-in/biometric-auth), [periodic background work](https://developer.android.com/develop/background-work/background-tasks/persistent/getting-started/define-work).

Independent personal project, not affiliated with Pluxee.
