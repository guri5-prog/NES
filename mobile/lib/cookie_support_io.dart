import 'package:cookie_jar/cookie_jar.dart';
import 'package:dio/dio.dart';
import 'package:dio_cookie_manager/dio_cookie_manager.dart';

class CookieSupport {
  final CookieJar _jar = CookieJar();

  void attach(Dio dio) {
    dio.interceptors.add(CookieManager(_jar));
  }

  Future<void> clear() => _jar.deleteAll();
}
