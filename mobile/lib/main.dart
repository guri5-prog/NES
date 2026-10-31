import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:geolocator/geolocator.dart';
import 'package:image_picker/image_picker.dart';
import 'package:latlong2/latlong.dart';

import 'cookie_support.dart';

String get apiBaseUrl {
  const envUrl = String.fromEnvironment('API_BASE_URL', defaultValue: '');
  if (envUrl.isNotEmpty) return envUrl;
  if (kIsWeb) return 'http://localhost:8000';
  return 'http://10.0.2.2:8000';
}

void main() {
  runApp(const NorthstarApp());
}

class ApiClient {
  ApiClient._() {
    dio = Dio(BaseOptions(
      baseUrl: apiBaseUrl,
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 15),
      headers: {'Accept': 'application/json'},
    ));
    cookieSupport.attach(dio);
  }

  static final ApiClient instance = ApiClient._();
  final CookieSupport cookieSupport = CookieSupport();
  late final Dio dio;

  Future<Map<String, dynamic>> login(String email, String password) async {
    final response = await dio.post<Map<String, dynamic>>(
      '/api/auth/login',
      data: {'email': email.trim(), 'password': password},
    );
    return Map<String, dynamic>.from(response.data?['user'] as Map);
  }

  Future<Map<String, dynamic>> register(String name, String email, String password) async {
    final response = await dio.post<Map<String, dynamic>>(
      '/api/auth/register',
      data: {'name': name.trim(), 'email': email.trim(), 'password': password},
    );
    return Map<String, dynamic>.from(response.data?['user'] as Map);
  }

  Future<Map<String, dynamic>?> currentUser() async {
    try {
      final response = await dio.get<Map<String, dynamic>>('/api/auth/session');
      final user = response.data?['user'];
      return user is Map ? Map<String, dynamic>.from(user) : null;
    } on DioException catch (error) {
      if (error.response?.statusCode == 401) return null;
      rethrow;
    }
  }

  Future<void> logout() async {
    await dio.post<void>('/api/auth/logout');
    await cookieSupport.clear();
  }

  String messageFor(Object error) {
    if (error is DioException) {
      final data = error.response?.data;
      if (data is Map && data['detail'] is String) {
        return data['detail'] as String;
      }
      if (error.type == DioExceptionType.receiveTimeout ||
          error.type == DioExceptionType.sendTimeout) {
        return 'The backend took too long to respond. Keep it running and try again.';
      }
      if (error.response == null) {
        return 'Could not reach the backend at $apiBaseUrl. Check that it is running.';
      }
    }
    return 'Something went wrong. Please try again.';
  }
}

class NorthstarApp extends StatelessWidget {
  const NorthstarApp({super.key});

  @override
  Widget build(BuildContext context) {
    const navy = Color(0xFF12233F);
    return MaterialApp(
      title: 'Northstar Logistics',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF315FE7)),
        scaffoldBackgroundColor: const Color(0xFFF3F6FA),
        appBarTheme: const AppBarTheme(
          backgroundColor: Colors.white,
          foregroundColor: navy,
          elevation: 0,
          centerTitle: false,
        ),
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: Colors.white,
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(12),
            borderSide: const BorderSide(color: Color(0xFFDCE4EF)),
          ),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(12),
            borderSide: const BorderSide(color: Color(0xFFDCE4EF)),
          ),
        ),
      ),
      home: const AuthGate(),
    );
  }
}

class AuthGate extends StatefulWidget {
  const AuthGate({super.key});

  @override
  State<AuthGate> createState() => _AuthGateState();
}

class _AuthGateState extends State<AuthGate> {
  Map<String, dynamic>? _user;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _restoreSession();
  }

  Future<void> _restoreSession() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      _user = await ApiClient.instance.currentUser();
    } catch (error) {
      _error = ApiClient.instance.messageFor(error);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _signedIn(Map<String, dynamic> user) {
    setState(() {
      _user = user;
      _error = null;
    });
  }

  Future<void> _signOut() async {
    try {
      await ApiClient.instance.logout();
    } catch (_) {
      // Clear the local session even if the server cannot be reached.
      await ApiClient.instance.cookieSupport.clear();
    }
    if (mounted) setState(() => _user = null);
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (_user != null) {
      return HomeScreen(user: _user!, onSignOut: _signOut);
    }
    return LoginScreen(
      initialError: _error,
      onSignedIn: _signedIn,
      onRetry: _restoreSession,
    );
  }
}

class LoginScreen extends StatefulWidget {
  const LoginScreen({
    required this.onSignedIn,
    required this.onRetry,
    this.initialError,
    super.key,
  });

  final void Function(Map<String, dynamic>) onSignedIn;
  final Future<void> Function() onRetry;
  final String? initialError;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _nameController = TextEditingController();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  bool _busy = false;
  bool _hidePassword = true;
  bool _creatingAccount = false;
  String? _error;

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    _nameController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final user = _creatingAccount
          ? await ApiClient.instance.register(
              _nameController.text,
              _emailController.text,
              _passwordController.text,
            )
          : await ApiClient.instance.login(
              _emailController.text,
              _passwordController.text,
            );
      if (mounted) widget.onSignedIn(user);
    } catch (error) {
      if (mounted) setState(() => _error = ApiClient.instance.messageFor(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final shownError = _error ?? widget.initialError;
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 440),
              child: Card(
                color: Colors.white,
                elevation: 1,
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Form(
                    key: _formKey,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Container(
                          width: 56,
                          height: 56,
                          alignment: Alignment.center,
                          decoration: BoxDecoration(
                            color: const Color(0xFF315FE7),
                            borderRadius: BorderRadius.circular(16),
                          ),
                          child: const Text('N', style: TextStyle(color: Colors.white, fontSize: 30, fontWeight: FontWeight.bold)),
                        ),
                        const SizedBox(height: 22),
                        Text('Northstar', style: Theme.of(context).textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.bold)),
                        const SizedBox(height: 6),
                        Text('Logistics intelligence', style: TextStyle(color: Colors.blueGrey.shade600)),
                        const SizedBox(height: 28),
                        if (_creatingAccount) ...[
                          TextFormField(
                            controller: _nameController,
                            textCapitalization: TextCapitalization.words,
                            decoration: const InputDecoration(labelText: 'Name'),
                            validator: (value) => _creatingAccount && (value == null || value.trim().isEmpty) ? 'Enter your name.' : null,
                          ),
                          const SizedBox(height: 14),
                        ],
                        TextFormField(
                          controller: _emailController,
                          keyboardType: TextInputType.emailAddress,
                          autofillHints: const [AutofillHints.username],
                          decoration: const InputDecoration(labelText: 'Email'),
                          validator: (value) => value == null || !value.contains('@') ? 'Enter a valid email.' : null,
                        ),
                        const SizedBox(height: 14),
                        TextFormField(
                          controller: _passwordController,
                          obscureText: _hidePassword,
                          autofillHints: const [AutofillHints.password],
                          decoration: InputDecoration(
                            labelText: 'Password',
                            suffixIcon: IconButton(
                              onPressed: () => setState(() => _hidePassword = !_hidePassword),
                              icon: Icon(_hidePassword ? Icons.visibility : Icons.visibility_off),
                            ),
                          ),
                          validator: (value) => value == null || value.length < 8 ? 'Password must be at least 8 characters.' : null,
                          onFieldSubmitted: (_) => _submit(),
                        ),
                        if (shownError != null) ...[
                          const SizedBox(height: 14),
                          Text(shownError, style: const TextStyle(color: Colors.red)),
                          if (widget.initialError != null && _error == null)
                            TextButton(onPressed: widget.onRetry, child: const Text('Retry connection')),
                        ],
                        const SizedBox(height: 22),
                        FilledButton(
                          onPressed: _busy ? null : _submit,
                          style: FilledButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 16)),
                          child: Text(_busy ? (_creatingAccount ? 'Creating account…' : 'Signing in…') : _creatingAccount ? 'Create account' : 'Sign in'),
                        ),
                        TextButton(
                          onPressed: _busy ? null : () => setState(() {
                            _creatingAccount = !_creatingAccount;
                            _error = null;
                          }),
                          child: Text(_creatingAccount ? 'Already have an account? Sign in' : 'Create an account'),
                        ),
                        const SizedBox(height: 12),
                        Text('API: $apiBaseUrl', textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.blueGrey)),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

const northeastStates = [
  'Arunachal Pradesh',
  'Assam',
  'Manipur',
  'Meghalaya',
  'Mizoram',
  'Nagaland',
  'Sikkim',
  'Tripura',
];

class HomeScreen extends StatefulWidget {
  const HomeScreen({required this.user, required this.onSignOut, super.key});

  final Map<String, dynamic> user;
  final Future<void> Function() onSignOut;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _originController = TextEditingController(text: 'Gangtok');
  final _destinationController = TextEditingController(text: 'Namchi');
  String _originState = 'Sikkim';
  String _destinationState = 'Sikkim';
  Map<String, dynamic>? _origin;
  Map<String, dynamic>? _destination;
  List<Map<String, dynamic>> _originMatches = [];
  List<Map<String, dynamic>> _destinationMatches = [];
  Map<String, dynamic>? _routes;
  Map<String, dynamic>? _weather;
  List<Map<String, dynamic>> _vehicles = [];
  List<Map<String, dynamic>> _incidents = [];
  Map<String, dynamic>? _landslides;
  String _selectedRoute = 'normal';
  bool _showCoolr = false;
  bool _showLhasa = false;
  bool _simulateCongestion = false;
  bool _loadingOverview = false;
  bool _loadingLandslides = false;
  int _tabIndex = 0;
  String? _error;
  String _searchingPlace = '';
  bool _findingRoutes = false;

  @override
  void initState() {
    super.initState();
    _origin = {'name': 'Gangtok', 'lat': 27.3389, 'lon': 88.6138};
    _destination = {'name': 'Namchi', 'lat': 27.1667, 'lon': 88.3639};
    _loadOverview();
  }

  @override
  void dispose() {
    _originController.dispose();
    _destinationController.dispose();
    super.dispose();
  }

  Future<void> _findPlace(bool origin) async {
    final controller = origin ? _originController : _destinationController;
    final state = origin ? _originState : _destinationState;
    if (controller.text.trim().length < 3) {
      setState(() => _error = 'Enter at least three characters to search for a place.');
      return;
    }
    final key = origin ? 'origin' : 'destination';
    setState(() {
      _searchingPlace = key;
      _error = null;
    });
    try {
      final response = await ApiClient.instance.dio.get<Map<String, dynamic>>(
        '/api/places/search',
        queryParameters: {'q': controller.text.trim(), 'state': state},
      );
      final matches = (response.data?['results'] as List? ?? [])
          .whereType<Map>()
          .map((item) => Map<String, dynamic>.from(item))
          .toList();
      if (!mounted) return;
      setState(() {
        if (origin) {
          _originMatches = matches;
        } else {
          _destinationMatches = matches;
        }
        if (matches.isEmpty) _error = 'No matching places found in $state.';
      });
    } catch (error) {
      if (mounted) setState(() => _error = ApiClient.instance.messageFor(error));
    } finally {
      if (mounted) setState(() => _searchingPlace = '');
    }
  }

  void _selectPlace(bool origin, Map<String, dynamic> place) {
    final title = place['display_name']?.toString() ?? place['name']?.toString() ?? '';
    setState(() {
      if (origin) {
        _origin = place;
        _originController.text = title;
        _originMatches = [];
      } else {
        _destination = place;
        _destinationController.text = title;
        _destinationMatches = [];
      }
      _routes = null;
      _weather = null;
      _landslides = null;
      _simulateCongestion = false;
      _error = null;
    });
  }

  Future<void> _calculateRoutes() async {
    if (_origin == null || _destination == null) {
      setState(() => _error = 'Search for and select both places before finding routes.');
      return;
    }
    setState(() {
      _findingRoutes = true;
      _error = null;
      _routes = null;
      _weather = null;
    });
    try {
      final response = await ApiClient.instance.dio.get<Map<String, dynamic>>(
        '/api/routes',
        options: Options(
          connectTimeout: const Duration(seconds: 15),
          receiveTimeout: const Duration(seconds: 90),
        ),
        queryParameters: {
          'state': _originState == _destinationState ? _originState : 'Northeast India',
          'origin_state': _originState,
          'destination_state': _destinationState,
          'start_lon': _origin!['lon'],
          'start_lat': _origin!['lat'],
          'destination_lon': _destination!['lon'],
          'destination_lat': _destination!['lat'],
        },
      );
      final data = response.data ?? {};
      if (mounted) {
        setState(() {
          _routes = data;
          _selectedRoute = 'normal';
          _landslides = null;
          _showCoolr = false;
          _showLhasa = false;
          _simulateCongestion = false;
          final conditions = data['route_conditions'];
          _weather = conditions is Map && conditions['normal'] is Map
              ? Map<String, dynamic>.from(conditions['normal'] as Map)
              : null;
        });
      }
    } catch (error) {
      if (mounted) setState(() => _error = ApiClient.instance.messageFor(error));
    } finally {
      if (mounted) setState(() => _findingRoutes = false);
    }
  }

  Future<void> _loadOverview() async {
    setState(() => _loadingOverview = true);
    try {
      final results = await Future.wait([
        ApiClient.instance.dio.get<Map<String, dynamic>>('/api/vehicles'),
        ApiClient.instance.dio.get<Map<String, dynamic>>('/api/incidents'),
      ]);
      if (!mounted) return;
      setState(() {
        _vehicles = (results[0].data?['vehicles'] as List? ?? [])
            .whereType<Map>()
            .map((item) => Map<String, dynamic>.from(item))
            .toList();
        _incidents = (results[1].data?['incidents'] as List? ?? [])
            .whereType<Map>()
            .map((item) => Map<String, dynamic>.from(item))
            .toList();
      });
    } catch (error) {
      if (mounted) setState(() => _error = ApiClient.instance.messageFor(error));
    } finally {
      if (mounted) setState(() => _loadingOverview = false);
    }
  }

  Map<String, dynamic>? get _activeRoute {
    final route = _routes?[_selectedRoute == 'normal' ? 'normal' : 'safer'];
    return route is Map ? Map<String, dynamic>.from(route) : null;
  }

  double? _effectiveRisk(Map<String, dynamic>? route, {bool primary = false}) {
    final value = route?['risk_score'];
    if (value is! num) return null;
    final baseline = value.toDouble();
    if (!_simulateCongestion || !primary) return baseline;
    return (baseline * 0.69 + 45 * 0.16 + 85 * 0.15)
        .clamp(baseline, 100.0)
        .toDouble();
  }

  Future<void> _loadLandslides() async {
    final coordinates = [
      ...((_routes?['normal'] as Map?)?['coordinates'] as List? ?? []),
      ...((_routes?['safer'] as Map?)?['coordinates'] as List? ?? []),
    ].whereType<List>().where((point) => point.length >= 2).toList();
    if (coordinates.length < 2) return;
    final lons = coordinates.map((point) => (point[0] as num).toDouble()).toList();
    final lats = coordinates.map((point) => (point[1] as num).toDouble()).toList();
    final params = {
      'west': (lons.reduce((a, b) => a < b ? a : b) - 0.12).toString(),
      'south': (lats.reduce((a, b) => a < b ? a : b) - 0.12).toString(),
      'east': (lons.reduce((a, b) => a > b ? a : b) + 0.12).toString(),
      'north': (lats.reduce((a, b) => a > b ? a : b) + 0.12).toString(),
      'days': '7',
    };
    setState(() {
      _loadingLandslides = true;
      _error = null;
    });
    try {
      final response = await ApiClient.instance.dio.get<Map<String, dynamic>>(
        '/api/landslides',
        queryParameters: params,
        options: Options(receiveTimeout: const Duration(seconds: 45)),
      );
      if (mounted) {
        setState(() {
          _landslides = response.data;
          _showCoolr = true;
          _showLhasa = false;
        });
      }
    } catch (error) {
      if (mounted) setState(() => _error = ApiClient.instance.messageFor(error));
    } finally {
      if (mounted) setState(() => _loadingLandslides = false);
    }
  }

  void _incidentAdded(Map<String, dynamic> incident) {
    setState(() {
      _incidents = [incident, ..._incidents];
      _tabIndex = 0;
    });
    _loadOverview();
  }

  Widget _placeField({required bool origin}) {
    final key = origin ? 'origin' : 'destination';
    final state = origin ? _originState : _destinationState;
    final controller = origin ? _originController : _destinationController;
    final results = origin ? _originMatches : _destinationMatches;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(origin ? 'Start location' : 'Destination', style: const TextStyle(fontWeight: FontWeight.w600)),
        const SizedBox(height: 7),
        DropdownButtonFormField<String>(
          value: state,
          isExpanded: true,
          decoration: const InputDecoration(labelText: 'State'),
          items: northeastStates.map((name) => DropdownMenuItem(value: name, child: Text(name, overflow: TextOverflow.ellipsis))).toList(),
          onChanged: (value) {
            if (value == null) return;
            setState(() {
              if (origin) {
                _originState = value;
                _origin = null;
                _originMatches = [];
              } else {
                _destinationState = value;
                _destination = null;
                _destinationMatches = [];
              }
              _routes = null;
            });
          },
        ),
        const SizedBox(height: 8),
        TextField(
          controller: controller,
          decoration: const InputDecoration(labelText: 'Place name', hintText: 'e.g. Gangtok'),
          onChanged: (_) => setState(() {
            if (origin) {
              _origin = null;
              _originMatches = [];
            } else {
              _destination = null;
              _destinationMatches = [];
            }
            _routes = null;
          }),
        ),
        const SizedBox(height: 8),
        OutlinedButton.icon(
          onPressed: _searchingPlace == key ? null : () => _findPlace(origin),
          icon: _searchingPlace == key
              ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
              : const Icon(Icons.search),
          label: Text(_searchingPlace == key ? 'Searching…' : 'Find place in $state'),
        ),
        if (results.isNotEmpty)
          Card(
            color: Colors.white,
            child: Column(
              children: results.map((place) => ListTile(
                dense: true,
                title: Text(place['name']?.toString() ?? 'Place', maxLines: 1, overflow: TextOverflow.ellipsis),
                subtitle: Text(place['display_name']?.toString() ?? '', maxLines: 2, overflow: TextOverflow.ellipsis),
                onTap: () => _selectPlace(origin, place),
              )).toList(),
            ),
          ),
      ],
    );
  }

  Widget _routeCard(String title, Map<String, dynamic>? route,
      {required String routeKey, required bool primary}) {
    final distance = route?['distance_km'];
    final risk = _effectiveRisk(route, primary: primary);
    final level = route?['risk_level']?.toString() ?? 'UNKNOWN';
    final duration = route?['duration_minutes'];
    final available = (route?['coordinates'] as List?)?.length != null &&
        (route?['coordinates'] as List).length > 1;
    final riskText = risk == null
        ? 'Not enough live data'
        : '${risk.toStringAsFixed(1)} / 100 · ${risk >= 65 ? 'high' : risk >= 35 ? 'medium' : level.toLowerCase()}';
    return Card(
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: BorderSide(
          color: _selectedRoute == routeKey ? const Color(0xFF315FE7) : Colors.transparent,
          width: 1.5,
        ),
      ),
      color: Colors.white,
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: available ? () => setState(() => _selectedRoute = routeKey) : null,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
              const SizedBox(height: 10),
              Text(distance is num ? '${distance.toStringAsFixed(1)} km' : 'No route available', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.bold)),
              if (duration is num) Text('About ${duration.round()} min', style: TextStyle(color: Colors.blueGrey.shade600)),
              const SizedBox(height: 8),
              Text('Risk: $riskText', style: TextStyle(color: risk != null && risk >= 35 ? Colors.deepOrange : Colors.teal.shade700, fontWeight: FontWeight.w600)),
            ],
          ),
        ),
      ),
    );
  }

  Color _riskColor(Object? rawBand, Object? rawScore) {
    final band = rawBand?.toString();
    final score = rawScore is num ? rawScore.toDouble() : 0.0;
    if (band == 'congested_high' || band == 'elevated' || score >= 35) return const Color(0xFFDC2626);
    if (band == 'congested_mild') return const Color(0xFFF97316);
    if (band == 'caution' || score >= 15) return const Color(0xFFEAB308);
    return const Color(0xFF2563EB);
  }

  List<LatLng> _latLngs(Object? rawCoordinates) {
    if (rawCoordinates is! List) return [];
    return rawCoordinates.whereType<List>().where((point) => point.length >= 2)
        .map((point) => LatLng((point[1] as num).toDouble(), (point[0] as num).toDouble())).toList();
  }

  List<LatLng> _routeSlice(List<LatLng> points, double start, double end) {
    if (points.length < 2) return [];
    LatLng at(double fraction) {
      final position = fraction * (points.length - 1);
      final index = position.floor().clamp(0, points.length - 2).toInt();
      final ratio = position - index;
      return LatLng(
        points[index].latitude + (points[index + 1].latitude - points[index].latitude) * ratio,
        points[index].longitude + (points[index + 1].longitude - points[index].longitude) * ratio,
      );
    }
    final from = start * (points.length - 1);
    final to = end * (points.length - 1);
    final slice = <LatLng>[at(start)];
    for (var index = from.floor() + 1; index <= to.floor(); index++) {
      if (index < points.length) slice.add(points[index]);
    }
    slice.add(at(end));
    return slice;
  }

  Widget _mapCard() {
    final normal = _routes?['normal'] as Map?;
    final safer = _routes?['safer'] as Map?;
    final primaryPoints = _latLngs(normal?['coordinates']);
    final alternativePoints = _latLngs(safer?['coordinates']);
    final allPoints = [...primaryPoints, ...alternativePoints];
    if (allPoints.length < 2) return const SizedBox.shrink();

    final lines = <Polyline>[];
    if (primaryPoints.length > 1) {
      lines.add(Polyline(points: primaryPoints, color: const Color(0xFF2563EB), strokeWidth: 7));
      final sections = normal?['risk_sections'];
      if (sections is List) {
        for (final section in sections.whereType<Map>()) {
          final points = _latLngs(section['coordinates']);
          if (points.length > 1) {
            lines.add(Polyline(points: points, color: _riskColor(section['risk_band'], section['max_risk_indicator']), strokeWidth: 8));
          }
        }
      }
    }
    if (alternativePoints.length > 1 && _routes?['has_alternative'] == true) {
      lines.add(Polyline(
        points: alternativePoints,
        color: const Color(0xFF15945A),
        strokeWidth: _selectedRoute == 'safer' ? 7 : 4,
        pattern: StrokePattern.dashed(segments: [10, 8]),
      ));
    }
    if (_simulateCongestion && primaryPoints.length > 2) {
      lines.add(Polyline(points: _routeSlice(primaryPoints, .27, .43), color: const Color(0xFFF97316), strokeWidth: 10));
      lines.add(Polyline(points: _routeSlice(primaryPoints, .67, .82), color: const Color(0xFFDC2626), strokeWidth: 10));
    }

    final polygons = <Polygon>[];
    final circles = <CircleMarker>[];
    if (_showCoolr) {
      final layers = _landslides?['layers'];
      final polygonCollection = layers is Map ? layers['polygons'] : null;
      final polygonFeatures = polygonCollection is Map ? polygonCollection['features'] : null;
      if (polygonFeatures is List) {
        for (final feature in polygonFeatures.whereType<Map>()) {
          final geometry = feature['geometry'];
          if (geometry is! Map) continue;
          final type = geometry['type'];
          final raw = geometry['coordinates'];
          final rings = <List>[];
          if (type == 'Polygon' && raw is List && raw.isNotEmpty && raw.first is List) {
            rings.add(raw.first as List);
          } else if (type == 'MultiPolygon' && raw is List) {
            for (final polygon in raw.whereType<List>()) {
              if (polygon.isNotEmpty && polygon.first is List) rings.add(polygon.first as List);
            }
          }
          for (final ring in rings) {
            final points = _latLngs(ring);
            if (points.length >= 3) polygons.add(Polygon(points: points, color: const Color(0x55EF4444), borderColor: const Color(0xFFB91C1C), borderStrokeWidth: 2));
          }
        }
      }
      final pointCollection = layers is Map ? layers['points'] : null;
      final pointFeatures = pointCollection is Map ? pointCollection['features'] : null;
      if (pointFeatures is List) {
        for (final feature in pointFeatures.whereType<Map>()) {
          final geometry = feature['geometry'];
          final coordinates = geometry is Map ? geometry['coordinates'] : null;
          if (coordinates is List && coordinates.length >= 2) {
            circles.add(CircleMarker(point: LatLng((coordinates[1] as num).toDouble(), (coordinates[0] as num).toDouble()), radius: 7, color: const Color(0xFFDC2626), borderColor: Colors.white, borderStrokeWidth: 2));
          }
        }
      }
    }

    final markers = <Marker>[];
    void addMarker(Object? lat, Object? lon, IconData icon, Color color, String label) {
      if (lat is num && lon is num) {
        markers.add(Marker(point: LatLng(lat.toDouble(), lon.toDouble()), width: 38, height: 42, alignment: Alignment.topCenter,
          child: Tooltip(message: label, child: Icon(icon, color: color, size: 34))));
      }
    }
    for (final vehicle in _vehicles) addMarker(vehicle['lat'], vehicle['lon'], Icons.local_shipping, const Color(0xFF2563EB), vehicle['id']?.toString() ?? 'Vehicle');
    for (final incident in _incidents) addMarker(incident['lat'], incident['lon'], Icons.warning_rounded, const Color(0xFFDC2626), incident['type']?.toString() ?? 'Incident');
    if (primaryPoints.isNotEmpty) {
      addMarker(primaryPoints.first.latitude, primaryPoints.first.longitude, Icons.trip_origin, const Color(0xFF15945A), 'Route start');
      addMarker(primaryPoints.last.latitude, primaryPoints.last.longitude, Icons.location_on, const Color(0xFF2563EB), 'Route destination');
    }
    if (_simulateCongestion && primaryPoints.length > 2) {
      for (final fraction in [.33, .73]) {
        final position = _routeSlice(primaryPoints, fraction, fraction + .001).first;
        addMarker(position.latitude, position.longitude, Icons.local_shipping, const Color(0xFF1685C4), 'Simulated vehicle');
      }
    }

    final lhasa = _landslides?['lhasa'];
    final lhasaBounds = lhasa is Map ? lhasa['bounds'] : null;
    final overlayImages = <OverlayImage>[];
    if (_showLhasa && lhasa is Map && lhasa['image_url'] is String && lhasaBounds is List && lhasaBounds.length == 2) {
      final southwest = lhasaBounds[0] as List;
      final northeast = lhasaBounds[1] as List;
      overlayImages.add(OverlayImage(
        bounds: LatLngBounds(LatLng((southwest[0] as num).toDouble(), (southwest[1] as num).toDouble()), LatLng((northeast[0] as num).toDouble(), (northeast[1] as num).toDouble())),
        imageProvider: NetworkImage(lhasa['image_url'] as String), opacity: .45,
      ));
    }

    return Card(
      color: Colors.white,
      clipBehavior: Clip.antiAlias,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Padding(padding: const EdgeInsets.all(16), child: Row(children: [
          Expanded(child: Text('Route and fleet map', style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold))),
          IconButton(onPressed: _loadingOverview ? null : _loadOverview, tooltip: 'Refresh vehicles and incidents', icon: const Icon(Icons.refresh)),
        ])),
        SizedBox(height: 350, child: FlutterMap(
          key: ValueKey('${_routes.hashCode}-${_landslides.hashCode}'),
          options: MapOptions(
            initialCenter: allPoints[allPoints.length ~/ 2],
            initialZoom: 5.5,
            initialCameraFit: CameraFit.bounds(bounds: LatLngBounds.fromPoints(allPoints), padding: const EdgeInsets.all(32)),
          ),
          children: [
            TileLayer(urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', userAgentPackageName: 'com.northstar.logistics.mobile'),
            if (polygons.isNotEmpty) PolygonLayer(polygons: polygons),
            if (lines.isNotEmpty) PolylineLayer(polylines: lines),
            if (circles.isNotEmpty) CircleLayer(circles: circles),
            if (overlayImages.isNotEmpty) OverlayImageLayer(overlayImages: overlayImages),
            if (markers.isNotEmpty) MarkerLayer(markers: markers),
            const RichAttributionWidget(attributions: [TextSourceAttribution('© OpenStreetMap contributors')]),
          ],
        )),
        Padding(padding: const EdgeInsets.all(12), child: Wrap(spacing: 12, runSpacing: 8, children: [
          _legend(Colors.blue, 'Primary'), _legend(Colors.green, 'Alternative'), _legend(Colors.orange, 'Mild congestion'), _legend(Colors.red, 'Elevated risk / incidents'),
        ])),
      ]),
    );
  }

  Widget _legend(Color color, String label) => Row(mainAxisSize: MainAxisSize.min, children: [
    Container(width: 14, height: 4, color: color), const SizedBox(width: 5), Text(label, style: const TextStyle(fontSize: 11)),
  ]);

  Widget _metricCard(IconData icon, String label, String value, String note, Color tint) =>
      SizedBox(width: 158, child: Card(color: Colors.white, child: Padding(padding: const EdgeInsets.all(14), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Icon(icon, color: tint), const SizedBox(height: 8), Text(value, style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold)), Text(label, style: const TextStyle(fontWeight: FontWeight.w600)), Text(note, maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 11, color: Colors.blueGrey.shade600)),
      ]))));

  Widget _dashboardBody() {
    final primary = _routes?['normal'] is Map ? Map<String, dynamic>.from(_routes!['normal'] as Map) : null;
    final alternative = _routes?['safer'] is Map ? Map<String, dynamic>.from(_routes!['safer'] as Map) : null;
    final routeConditions = _routes?['route_conditions'];
    final conditions = routeConditions is Map ? routeConditions[_selectedRoute] : null;
    final points = conditions is Map ? (conditions['points'] as List? ?? []) : [];
    final summary = conditions is Map && conditions['summary'] is Map ? conditions['summary'] as Map : const {};
    final rainfall = summary['maximum_rainfall_mm'];
    final selected = _activeRoute;
    final selectedRisk = _effectiveRisk(selected, primary: _selectedRoute == 'normal');
    final hasAlternative = _routes?['has_alternative'] == true;
    final riskFactors = selected?['risk_factors'] as List? ?? [];
    final selectedSections = selected?['segments'] as List? ?? [];
    final primaryRisk = _effectiveRisk(primary, primary: true);
    final alternativeRisk = _effectiveRisk(alternative);
    return RefreshIndicator(
      onRefresh: _loadOverview,
      child: ListView(padding: const EdgeInsets.all(16), children: [
        Text('Good day${widget.user['name'] == null ? '' : ', ${widget.user['name']}'}', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.bold)),
        const SizedBox(height: 4),
        const Text('Monitor route conditions, incidents, and fleet activity.'),
        const SizedBox(height: 12),
        Wrap(spacing: 6, runSpacing: 4, children: [
          _metricCard(Icons.local_shipping_outlined, 'Tracked vehicles', '${_vehicles.length}', 'Vehicles reporting position', const Color(0xFF315FE7)),
          _metricCard(Icons.warning_amber_rounded, 'Active incidents', '${_incidents.length}', 'Reported incidents', const Color(0xFFE99A19)),
          _metricCard(Icons.umbrella_outlined, 'Route rainfall', rainfall is num ? '${rainfall.toStringAsFixed(1)} mm' : '—', _routes == null ? 'Find a route first' : 'Maximum at sampled points', const Color(0xFF7650C8)),
          _metricCard(Icons.alt_route, 'Route risk', selectedRisk == null ? '—' : '${selectedRisk.toStringAsFixed(1)} / 100', selected?['risk_level']?.toString() ?? 'Not assessed', const Color(0xFF15945A)),
        ]),
        const SizedBox(height: 12),
        Card(color: Colors.white, child: Padding(padding: const EdgeInsets.all(16), child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text('Find a route', style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold)),
          const SizedBox(height: 14),
          _placeField(origin: true),
          const SizedBox(height: 16),
          _placeField(origin: false),
          const SizedBox(height: 14),
          FilledButton.icon(
            onPressed: _findingRoutes ? null : _calculateRoutes,
            icon: _findingRoutes ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)) : const Icon(Icons.alt_route),
            label: Text(_findingRoutes ? 'Finding routes…' : 'Find routes'),
          ),
          if (_error != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(_error!, style: const TextStyle(color: Colors.red))),
        ]))),
        if (_routes != null) ...[
          const SizedBox(height: 12),
          Text('Available routes', style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold)),
          _routeCard('Primary route', primary, routeKey: 'normal', primary: true),
          _routeCard('Alternative route', hasAlternative ? alternative : null, routeKey: 'safer', primary: false),
          Card(color: Colors.white, child: Padding(padding: const EdgeInsets.all(16), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${_selectedRoute == 'normal' ? 'Primary' : 'Alternative'} route risk', style: const TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 6),
            Text(selectedRisk == null ? 'Not enough route data to calculate a score.' : '${selectedRisk.toStringAsFixed(1)} / 100 · ${(selectedRisk >= 65 ? 'High' : selectedRisk >= 35 ? 'Medium' : 'Low')} risk', style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold, color: selectedRisk != null && selectedRisk >= 35 ? Colors.deepOrange : Colors.teal)),
            if (_simulateCongestion) const Text('Includes simulated congestion; not a live traffic reading.', style: TextStyle(fontSize: 12)),
            if (riskFactors.isNotEmpty) ...[const SizedBox(height: 8), const Text('What affects this route', style: TextStyle(fontWeight: FontWeight.w600)), ...riskFactors.take(4).map((factor) => Text('• $factor'))],
            if (selectedSections.isNotEmpty) ...[const SizedBox(height: 8), const Text('Highest scoring sections', style: TextStyle(fontWeight: FontWeight.w600)), ...selectedSections.take(3).map((segment) => Text('• ${segment['risk_indicator'] ?? '—'}/100 · ${segment['distance_km'] ?? '—'} km'))],
            if (primaryRisk != null && alternativeRisk != null && hasAlternative) Text('Alternative route risk: ${alternativeRisk.toStringAsFixed(1)} / 100. ${primaryRisk > alternativeRisk ? 'It currently scores lower.' : 'Both routes have similar or lower estimated risk.'}', style: const TextStyle(fontSize: 12)),
          ]))),
          const SizedBox(height: 8),
          Card(color: Colors.white, child: Column(children: [
            SwitchListTile(title: const Text('Simulate congestion'), subtitle: const Text('Orange shows mild; red shows heavy simulated congestion.'), value: _simulateCongestion, onChanged: (value) => setState(() => _simulateCongestion = value)),
            ListTile(leading: const Icon(Icons.landscape_outlined), title: const Text('Reported landslides (7 days)'), trailing: _loadingLandslides ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : TextButton(onPressed: _loadLandslides, child: const Text('Load'))),
            if (_landslides != null) ...[
              SwitchListTile(title: const Text('COOLR reports'), value: _showCoolr, onChanged: (value) => setState(() => _showCoolr = value)),
              SwitchListTile(title: const Text('LHASA regional hazard'), value: _showLhasa, onChanged: (value) => setState(() => _showLhasa = value)),
            ],
          ])),
          _mapCard(),
          Card(color: Colors.white, child: Padding(padding: const EdgeInsets.all(16), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${_selectedRoute == 'normal' ? 'Primary' : 'Alternative'} route weather', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
            Text('Rainfall along route: ${rainfall is num ? '${rainfall.toStringAsFixed(1)} mm maximum at sampled points' : 'No current rainfall reading'}'),
            if (points.isNotEmpty) ...[
              const SizedBox(height: 8),
              ...points.whereType<Map>().map((point) => Padding(padding: const EdgeInsets.symmetric(vertical: 3), child: Text('${point['position'] ?? 'Route'}  ·  Rain ${point['rainfall_mm'] == null ? '—' : '${point['rainfall_mm']} mm'}  ·  Visibility ${point['visibility_km'] == null ? '—' : '${point['visibility_km']} km'}  ·  ${point['temperature_c'] == null ? '—' : '${point['temperature_c']}°C'}', style: const TextStyle(fontSize: 12)))),
            ],
            const SizedBox(height: 6),
            const Text('Risk is a heuristic estimate, not a disruption probability or confirmed road closure.', style: TextStyle(fontSize: 11, color: Colors.blueGrey)),
          ]))),
        ],
        const SizedBox(height: 10),
        Text('Recent incidents (${_incidents.length})', style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold)),
        if (_incidents.isEmpty) const Card(color: Colors.white, child: ListTile(title: Text('No reported incidents yet.'))),
        ..._incidents.take(10).map((incident) => Card(color: Colors.white, child: ListTile(
          leading: Icon(Icons.warning_amber_rounded, color: incident['severity'] == 'HIGH' ? Colors.red : Colors.orange),
          title: Text((incident['type']?.toString() ?? 'Incident').replaceAll('_', ' ')),
          subtitle: Text('${incident['description'] ?? ''}${incident['lat'] != null ? '\n${incident['lat']}, ${incident['lon']}' : ''}', maxLines: 3, overflow: TextOverflow.ellipsis),
          trailing: incident['photo_url'] == null ? null : const Icon(Icons.photo_camera_outlined),
        ))),
        if (_loadingOverview) const Padding(padding: EdgeInsets.all(20), child: Center(child: CircularProgressIndicator())),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Northstar'),
        actions: [
          IconButton(
            tooltip: 'Refresh dashboard',
            onPressed: _loadingOverview ? null : _loadOverview,
            icon: const Icon(Icons.refresh),
          ),
          IconButton(tooltip: 'Sign out', onPressed: widget.onSignOut, icon: const Icon(Icons.logout)),
        ],
      ),
      body: IndexedStack(
        index: _tabIndex,
        children: [
          _dashboardBody(),
          IncidentReportForm(onSubmitted: _incidentAdded),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tabIndex,
        onDestinationSelected: (index) => setState(() => _tabIndex = index),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.dashboard_outlined), selectedIcon: Icon(Icons.dashboard), label: 'Dashboard'),
          NavigationDestination(icon: Icon(Icons.add_location_alt_outlined), selectedIcon: Icon(Icons.add_location_alt), label: 'Report'),
        ],
      ),
    );
  }
}

class IncidentReportForm extends StatefulWidget {
  const IncidentReportForm({required this.onSubmitted, super.key});

  final void Function(Map<String, dynamic>) onSubmitted;

  @override
  State<IncidentReportForm> createState() => _IncidentReportFormState();
}

class _IncidentReportFormState extends State<IncidentReportForm> {
  final _formKey = GlobalKey<FormState>();
  final _descriptionController = TextEditingController();
  final _latitudeController = TextEditingController();
  final _longitudeController = TextEditingController();
  final _picker = ImagePicker();
  String _type = 'ROAD_BLOCK';
  String _severity = 'MEDIUM';
  XFile? _photo;
  Uint8List? _photoBytes;
  bool _gettingLocation = false;
  bool _submitting = false;
  String? _message;
  bool _messageIsError = false;

  @override
  void dispose() {
    _descriptionController.dispose();
    _latitudeController.dispose();
    _longitudeController.dispose();
    super.dispose();
  }

  Future<void> _addPhoto(ImageSource source) async {
    try {
      final selected = await _picker.pickImage(source: source, imageQuality: 85, maxWidth: 1800);
      if (selected == null) return;
      final photoBytes = await selected.readAsBytes();
      setState(() {
        _photo = selected;
        _photoBytes = photoBytes;
        _gettingLocation = true;
        _message = 'Photo selected. Getting its report location…';
        _messageIsError = false;
      });
      final serviceEnabled = await Geolocator.isLocationServiceEnabled();
      if (!serviceEnabled) throw Exception('Enable Location on your phone to fill coordinates automatically.');
      var permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) permission = await Geolocator.requestPermission();
      if (permission == LocationPermission.denied || permission == LocationPermission.deniedForever) {
        throw Exception('Location permission is needed for automatic coordinates. You can enter them manually.');
      }
      final position = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(accuracy: LocationAccuracy.high, timeLimit: Duration(seconds: 20)),
      );
      _latitudeController.text = position.latitude.toStringAsFixed(6);
      _longitudeController.text = position.longitude.toStringAsFixed(6);
      setState(() {
        _message = 'Photo added and coordinates filled from the phone’s current location.';
        _messageIsError = false;
      });
    } catch (error) {
      setState(() {
        _message = error.toString().replaceFirst('Exception: ', '');
        _messageIsError = true;
      });
    } finally {
      if (mounted) setState(() => _gettingLocation = false);
    }
  }

  Future<void> _choosePhoto() async {
    final source = await showModalBottomSheet<ImageSource>(
      context: context,
      builder: (context) => SafeArea(child: Wrap(children: [
        if (!kIsWeb) ListTile(leading: const Icon(Icons.photo_camera), title: const Text('Take a photo'), onTap: () => Navigator.pop(context, ImageSource.camera)),
        ListTile(leading: const Icon(Icons.photo_library), title: const Text('Choose from gallery'), onTap: () => Navigator.pop(context, ImageSource.gallery)),
      ])),
    );
    if (source != null) await _addPhoto(source);
  }

  String _photoContentType(String path) {
    final lower = path.toLowerCase();
    if (lower.endsWith('.png')) return 'image/png';
    if (lower.endsWith('.webp')) return 'image/webp';
    return 'image/jpeg';
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    final lat = double.tryParse(_latitudeController.text.trim());
    final lon = double.tryParse(_longitudeController.text.trim());
    if ((lat == null) != (lon == null)) {
      setState(() {
        _message = 'Enter both latitude and longitude, or clear both fields.';
        _messageIsError = true;
      });
      return;
    }
    if (_photo != null && (lat == null || lon == null)) {
      setState(() {
        _message = 'A photo report needs coordinates. Add a photo again with location enabled, or enter both coordinates.';
        _messageIsError = true;
      });
      return;
    }
    setState(() {
      _submitting = true;
      _message = null;
    });
    try {
      final Dio dio = ApiClient.instance.dio;
      final Response<Map<String, dynamic>> response;
      if (_photo != null) {
        final bytes = _photoBytes ?? await _photo!.readAsBytes();
        response = await dio.post<Map<String, dynamic>>(
          '/api/incidents/report',
          queryParameters: {
            'type': _type,
            'severity': _severity,
            'description': _descriptionController.text.trim(),
            'lat': lat,
            'lon': lon,
          },
          data: bytes,
          options: Options(
            contentType: _photoContentType(_photo!.path),
            receiveTimeout: const Duration(seconds: 45),
            sendTimeout: const Duration(seconds: 45),
          ),
        );
      } else {
        final body = <String, dynamic>{
          'type': _type,
          'severity': _severity,
          'description': _descriptionController.text.trim(),
        };
        if (lat != null && lon != null) {
          body['lat'] = lat;
          body['lon'] = lon;
        }
        response = await dio.post<Map<String, dynamic>>('/api/incidents', data: body);
      }
      final incident = Map<String, dynamic>.from(response.data?['incident'] as Map);
      widget.onSubmitted(incident);
      _descriptionController.clear();
      _latitudeController.clear();
      _longitudeController.clear();
      setState(() {
        _photo = null;
        _message = 'Incident report submitted.';
        _messageIsError = false;
      });
    } catch (error) {
      setState(() {
        _message = ApiClient.instance.messageFor(error);
        _messageIsError = true;
      });
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) => Form(
    key: _formKey,
    child: ListView(padding: const EdgeInsets.all(16), children: [
      Text('Report an incident', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.bold)),
      const SizedBox(height: 6),
      const Text('Share a road blockage, landslide, flood, accident, or visibility issue.'),
      const SizedBox(height: 16),
      Card(color: Colors.white, child: Padding(padding: const EdgeInsets.all(16), child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        DropdownButtonFormField<String>(
          value: _type,
          decoration: const InputDecoration(labelText: 'Incident type'),
          items: const [
            DropdownMenuItem(value: 'ROAD_BLOCK', child: Text('Road blockage')),
            DropdownMenuItem(value: 'LANDSLIDE', child: Text('Landslide')),
            DropdownMenuItem(value: 'FLOOD', child: Text('Flooding')),
            DropdownMenuItem(value: 'ACCIDENT', child: Text('Road accident')),
            DropdownMenuItem(value: 'LOW_VISIBILITY', child: Text('Low visibility')),
            DropdownMenuItem(value: 'OTHER', child: Text('Other')),
          ],
          onChanged: (value) => setState(() => _type = value ?? _type),
        ),
        const SizedBox(height: 12),
        DropdownButtonFormField<String>(
          value: _severity,
          decoration: const InputDecoration(labelText: 'Severity'),
          items: const [DropdownMenuItem(value: 'HIGH', child: Text('High')), DropdownMenuItem(value: 'MEDIUM', child: Text('Medium')), DropdownMenuItem(value: 'LOW', child: Text('Low'))],
          onChanged: (value) => setState(() => _severity = value ?? _severity),
        ),
        const SizedBox(height: 12),
        TextFormField(controller: _descriptionController, minLines: 3, maxLines: 5, maxLength: 2000, decoration: const InputDecoration(labelText: 'Description', hintText: 'Describe what happened and how the road is affected.'), validator: (value) => value == null || value.trim().isEmpty ? 'Add a short description.' : null),
        const SizedBox(height: 4),
        OutlinedButton.icon(
          onPressed: _gettingLocation || _submitting ? null : _choosePhoto,
          icon: _gettingLocation ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.add_a_photo_outlined),
          label: Text(_gettingLocation ? 'Getting location…' : _photo == null ? 'Add photo and fill location' : 'Change photo'),
        ),
        if (_photo != null) ...[
          const SizedBox(height: 10),
          ClipRRect(borderRadius: BorderRadius.circular(10), child: _photoBytes != null ? Image.memory(_photoBytes!, height: 190, fit: BoxFit.cover) : const SizedBox.shrink()),
          Align(alignment: Alignment.centerRight, child: TextButton.icon(onPressed: () => setState(() { _photo = null; _photoBytes = null; }), icon: const Icon(Icons.delete_outline), label: const Text('Remove photo'))),
        ],
        const SizedBox(height: 8),
        Row(children: [
          Expanded(child: TextFormField(controller: _latitudeController, keyboardType: const TextInputType.numberWithOptions(decimal: true, signed: true), decoration: const InputDecoration(labelText: 'Latitude', hintText: 'e.g. 27.33'))),
          const SizedBox(width: 10),
          Expanded(child: TextFormField(controller: _longitudeController, keyboardType: const TextInputType.numberWithOptions(decimal: true, signed: true), decoration: const InputDecoration(labelText: 'Longitude', hintText: 'e.g. 88.61'))),
        ]),
        const SizedBox(height: 8),
        const Text('Choosing a photo requests your current phone location and fills these fields automatically. You can edit them.', style: TextStyle(fontSize: 12, color: Colors.blueGrey)),
        if (_message != null) Padding(padding: const EdgeInsets.only(top: 10), child: Text(_message!, style: TextStyle(color: _messageIsError ? Colors.red : Colors.teal))),
        const SizedBox(height: 12),
        FilledButton.icon(onPressed: _submitting ? null : _submit, icon: _submitting ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)) : const Icon(Icons.send), label: Text(_submitting ? 'Submitting…' : 'Submit incident report')),
      ]))),
    ]),
  );
}
