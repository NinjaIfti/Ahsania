import 'package:amcgh_capture/main.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('opens the LAN dev server unless APP_URL is given', () {
    expect(appUrl, startsWith('http'));
  });
}
