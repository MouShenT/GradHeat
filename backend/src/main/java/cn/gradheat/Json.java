package cn.gradheat;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.json.JsonMapper;

/** Canonical UTF-8 JSON for messaging. Personal comparisons use Python's exact canonical bytes. */
public final class Json {
    public static final ObjectMapper MAPPER = JsonMapper.builder().enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS).build();
    private Json() {}
    public static JsonNode parse(String text) { return MAPPER.readTree(text); }
    public static String encode(Object value) { return MAPPER.writeValueAsString(value); }
    public static boolean equivalent(JsonNode left,JsonNode right) {
        if(left.isNumber() && right.isNumber())return new java.math.BigDecimal(left.toString()).compareTo(new java.math.BigDecimal(right.toString()))==0;
        if(left.isArray() && right.isArray()) {if(left.size()!=right.size())return false;for(int i=0;i<left.size();i++)if(!equivalent(left.get(i),right.get(i)))return false;return true;}
        if(left.isObject() && right.isObject()) {if(left.size()!=right.size())return false;for(var p:left.properties())if(right.get(p.getKey())==null || !equivalent(p.getValue(),right.get(p.getKey())))return false;return true;}
        return left.equals(right);
    }
    public static String canonical(Object value) {
        JsonNode node = value instanceof JsonNode j ? j : MAPPER.valueToTree(value);
        if (node.isObject()) {
            TreeMap<String, JsonNode> map = new TreeMap<>();
            node.properties().forEach(e -> map.put(e.getKey(), e.getValue()));
            return "{" + String.join(",", map.entrySet().stream().map(e -> quote(e.getKey()) + ":" + canonical(e.getValue())).toList()) + "}";
        }
        if (node.isArray()) { List<String> items = new ArrayList<>(); node.forEach(e -> items.add(canonical(e))); return "[" + String.join(",", items) + "]"; }
        return node.isString() ? quote(node.asString()) : node.toString();
    }
    public static String quote(String text) {
        StringBuilder b = new StringBuilder("\"");
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
            switch (c) {
                case '"' -> b.append("\\\""); case '\\' -> b.append("\\\\");
                case '\b' -> b.append("\\b"); case '\f' -> b.append("\\f");
                case '\n' -> b.append("\\n"); case '\r' -> b.append("\\r"); case '\t' -> b.append("\\t");
                default -> { if (c < 32) b.append(String.format("\\u%04x", (int)c)); else b.append(c); }
            }
        }
        return b.append('"').toString();
    }
    public static String sha(String text) { return sha(text.getBytes(StandardCharsets.UTF_8)); }
    public static String sha(byte[] value) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value)); }
        catch (Exception e) { throw new IllegalStateException(e); }
    }
}
