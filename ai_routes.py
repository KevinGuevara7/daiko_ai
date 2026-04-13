import 'dart:convert';
import 'package:http/http.dart' as http;
import '../model/chat_message.dart';

class AIService {
  final String _urlBase = 'https://daiko-ai.onrender.com/ai/consultar';

  Future<ChatMessage> sendMessageToDaiko(String prompt, String token) async {
    print("--- DEBUG FLUTTER SERVICE ---");
    print("URL: $_urlBase");
    print("TOKEN ENVIADO: Bearer ${token.substring(0, 5)}..."); // Solo el inicio por seguridad

    try {
      final url = Uri.parse('$_urlBase?pregunta=${Uri.encodeComponent(prompt)}');
      final response = await http.get(
        url,
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $token',
        },
      );

      print("DEBUG SERVER RESPONSE: ${response.statusCode}");
      print("DEBUG SERVER BODY: ${response.body}");

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        return ChatMessage(
          text: data['text'] ?? 'Sin respuesta de Daiko',
          sender: MessageSender.daiko,
          timestamp: DateTime.now(),
        );
      } else {
        // Si el servidor responde con error (401, 500, etc), lo capturamos aquí
        return ChatMessage(
          text: "Error ${response.statusCode}: ${response.body}",
          sender: MessageSender.daiko,
          timestamp: DateTime.now(),
        );
      }
    } catch (e) {
      print("DEBUG FATAL ERROR: $e");
      // ESTE ES EL RETURN QUE TE FALTABA PARA QUITAR EL ERROR ROJO
      return ChatMessage(
        text: "Error de conexión: No se pudo contactar al servidor.",
        sender: MessageSender.daiko,
        timestamp: DateTime.now(),
      );
    }
  }
}
