package cn.gradheat;

import java.time.Duration;
import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import tools.jackson.databind.JsonNode;

@Repository
public class PublicationRepository {
    private final JdbcTemplate jdbc;
    private final StringRedisTemplate redis;
    private final boolean redisEnabled;
    public record Publication(String version, JsonNode payload) {}
    public PublicationRepository(JdbcTemplate jdbc, StringRedisTemplate redis, @Value("${gradheat.redis-enabled:false}") boolean enabled) {
        this.jdbc=jdbc; this.redis=redis; this.redisEnabled=enabled;
    }
    public Publication current() {
        try {
            String version=jdbc.queryForObject("SELECT version_id FROM admissions_head WHERE name='current'",String.class);
            return byVersion(version);
        } catch(EmptyResultDataAccessException e) { throw new ApiFailure(503,"no_publication","尚无已发布招生资料"); }
    }
    public Publication byVersion(String version) {
        if(version==null || !version.matches("[0-9a-f]{64}")) throw new ApiFailure(404,"publication_missing","资料版本不存在");
        String key="gradheat:java:admissions:"+version;
        if(redisEnabled) {
            try {
                String cached=redis.opsForValue().get(key);
                if(cached!=null) {
                    JsonNode wrapper=Json.parse(cached);
                    String body=wrapper.path("body").asString();
                    if(version.equals(wrapper.path("version").asString()) && version.equals(Json.sha(body)) && Json.sha(body).equals(wrapper.path("body_sha").asString()))
                        return safe(version,body);
                    redis.delete(key);
                }
            } catch(Exception ignored) { /* Rebuild from MySQL; Redis is never authoritative. */ }
        }
        try {
            var record=jdbc.queryForMap("SELECT p.payload_json,b.content FROM admissions_publication p LEFT JOIN admissions_publication_bytes b ON b.version_id=p.version_id WHERE p.version_id=?",version);
            byte[] bytes=(byte[])record.get("content");
            if(bytes==null)throw new ApiFailure(503,"publication_bytes_missing","招生资料规范原件尚未归档");
            String body=new String(bytes,java.nio.charset.StandardCharsets.UTF_8);
            if(!version.equals(Json.sha(bytes)) || !Json.equivalent(Json.parse(body),Json.parse((String)record.get("payload_json"))))throw new ApiFailure(503,"publication_integrity","招生资料版本校验失败");
            Publication result=safe(version,body);
            if(redisEnabled) try { redis.opsForValue().set(key,Json.encode(Map.of("version",version,"body",body,"body_sha",Json.sha(body))),Duration.ofHours(26)); } catch(Exception ignored) {}
            return result;
        } catch(EmptyResultDataAccessException e) { throw new ApiFailure(404,"publication_missing","资料版本不存在"); }
    }
    private Publication safe(String version,String body) {
        if(!Json.sha(body).equals(version))throw new ApiFailure(503,"publication_integrity","招生资料版本校验失败");
        JsonNode payload=Json.parse(body);
        if(!payload.path("programmes").isArray() || !payload.path("units").isArray()) throw new ApiFailure(503,"invalid_publication","资料投影不完整");
        rejectPrivate(payload);
        return new Publication(version,payload);
    }
    static void rejectPrivate(JsonNode value) {
        Set<String> forbidden=Set.of("source_url","origin_url","local_path","private_log","cookie","cookies","request_headers","webSocketDebuggerUrl","artifact_sha256","content_sha256","transcript_sha256","raw_html","raw_text","transcript","artifact_path","download_path","session_path");
        if(value.isObject()) value.properties().forEach(e -> { if(forbidden.contains(e.getKey())) throw new ApiFailure(503,"unsafe_projection","公开资料投影需要审核"); rejectPrivate(e.getValue()); });
        else if(value.isArray()) value.forEach(PublicationRepository::rejectPrivate);
    }
}
