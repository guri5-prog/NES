import 'package:dio/dio.dart';
import 'package:dio_web_adapter/dio_web_adapter.dart';

class CookieSupport {
  void attach(Dio dio) {
    dio.httpClientAdapter = BrowserHttpClientAdapter(withCredentials: true);
  }

  Future<void> clear() async {
    // The browser clears the session cookie when the authenticated logout
    // endpoint responds with Set-Cookie and an expired cookie value.
  }
}
