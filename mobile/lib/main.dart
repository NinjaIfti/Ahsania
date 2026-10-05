import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_inappwebview/flutter_inappwebview.dart';

/// The web app this shell opens. Build with
/// `flutter build apk --dart-define=APP_URL=https://your-server`.
const appUrl = String.fromEnvironment('APP_URL', defaultValue: 'https://adynamic-trinh-thickly.ngrok-free.dev');

void main() => runApp(const MaterialApp(debugShowCheckedModeBanner: false, home: Shell()));

class Shell extends StatefulWidget {
  const Shell({super.key});

  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  InAppWebViewController? _web;
  String? _error;

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      // Android back goes back inside the web app; it only closes the app on the first page.
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop) return;
        if (_web != null && await _web!.canGoBack()) {
          await _web!.goBack();
        } else {
          await SystemNavigator.pop();
        }
      },
      child: Scaffold(
        body: SafeArea(
          child: Stack(children: [
            InAppWebView(
              initialUrlRequest: URLRequest(url: WebUri(appUrl)),
              initialSettings: InAppWebViewSettings(
                javaScriptEnabled: true,
                domStorageEnabled: true,
                databaseEnabled: true,
                allowFileAccess: true,
                mediaPlaybackRequiresUserGesture: false,
                userAgent: 'AMCGHCapture/1.0', // a non-browser agent skips ngrok's free-plan warning page
              ),
              onWebViewCreated: (c) => _web = c,
              onLoadStart: (_, _) => setState(() => _error = null),
              onReceivedError: (_, request, error) {
                if (request.isForMainFrame ?? true) setState(() => _error = error.description);
              },
            ),
            if (_error != null)
              Container(
                color: Colors.white,
                padding: const EdgeInsets.all(24),
                alignment: Alignment.center,
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  const Text("Can't reach the server", style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 8),
                  Text('$appUrl\n$_error', textAlign: TextAlign.center),
                  const SizedBox(height: 16),
                  FilledButton(onPressed: () => _web?.reload(), child: const Text('Try again')),
                ]),
              ),
          ]),
        ),
      ),
    );
  }
}
