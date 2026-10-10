package cn.gradheat;

import java.nio.charset.StandardCharsets;
import java.sql.Timestamp;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;

/** Reuses the existing immutable archive; Python alone renders and computes comparisons. */
@Repository
public class ComparisonArchive {
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    public ComparisonArchive(JdbcTemplate jdbc,TransactionTemplate tx) {this.jdbc=jdbc;this.tx=tx;}
    public Map<String,Object> save(JsonNode packageValue) {
        String raw=packageValue.path("canonical_result").asString(),archive=packageValue.path("canonical_archive").asString();
        String report=packageValue.path("report_md").asString(),id=packageValue.path("comparison_id").asString();
        JsonNode result=packageValue.path("result");
        if(raw.length()>4_000_000 || archive.length()>5_000_000 || !id.matches("[a-f0-9]{64}") || !Json.sha(archive).equals(id))throw new ApiFailure(502,"comparison_integrity","计算档案完整性校验失败");
        if(!Json.parse(raw).equals(result) || !archive.equals(archiveText(raw,report)))throw new ApiFailure(502,"comparison_integrity","计算档案字节与结果不一致");
        String dataVersion=result.path("data_version").asString(),analysis=result.path("analysis_version").asString(),title=result.path("input").path("title").asString();
        if(!dataVersion.matches("[a-f0-9]{64}") || title.isBlank() || title.length()>120 || analysis.isBlank() || analysis.length()>80 || !result.path("cards").isArray())throw new ApiFailure(502,"comparison_integrity","比较档案字段不完整");
        PublicationRepository.rejectPrivate(result);
        return tx.execute(s -> {
            var existing=jdbc.queryForList("SELECT comparison_id FROM personal_comparison WHERE comparison_id=?",id);
            boolean reused=!existing.isEmpty();
            if(!reused)jdbc.update("INSERT INTO personal_comparison(comparison_id,title,data_version,analysis_version,candidate_count,result_json,report_md,result_bytes) VALUES(?,?,?,?,?,?,?,?)",id,title,dataVersion,analysis,result.path("cards").size(),raw,report,raw.getBytes(StandardCharsets.UTF_8));
            Map<String,Object> stored=get(id);
            return Map.of("comparison_id",id,"reused",reused,"created_at",stored.get("created_at"),"title",title);
        });
    }
    static String archiveText(String raw,String report) {return "{\"report_md\":"+Json.quote(report)+",\"result\":"+raw+"}";}
    public Map<String,Object> get(String id) {
        if(id==null || !id.matches("[a-f0-9]{64}"))throw new ApiFailure(404,"comparison_missing","比较记录不存在");
        var rows=jdbc.queryForList("SELECT comparison_id,created_at,title,data_version,analysis_version,candidate_count,result_json,report_md,result_bytes FROM personal_comparison WHERE comparison_id=?",id);
        if(rows.isEmpty())throw new ApiFailure(404,"comparison_missing","比较记录不存在");
        Map<String,Object> value=JdbcMaps.lower(rows.getFirst());
        Object bytes=value.remove("result_bytes");
        String raw=bytes instanceof byte[] b?new String(b,StandardCharsets.UTF_8):Json.canonical(Json.parse((String)value.get("result_json")));
        String report=(String)value.get("report_md");
        if(!Json.sha(archiveText(raw,report)).equals(id))throw new ApiFailure(409,"comparison_integrity","已存比较记录内容校验失败");
        value.remove("result_json");JsonNode result=Json.parse(raw);PublicationRepository.rejectPrivate(result);value.put("result",result);
        Object created=value.get("created_at");if(created instanceof Timestamp t)value.put("created_at",t.toInstant().toString());
        return value;
    }
    public List<Map<String,Object>> list() {
        return jdbc.queryForList("SELECT comparison_id,created_at,title,candidate_count FROM personal_comparison ORDER BY created_at DESC,comparison_id LIMIT 100").stream().map(row->{Map<String,Object> value=JdbcMaps.lower(row);Object time=value.get("created_at");if(time instanceof Timestamp t)value.put("created_at",t.toInstant().toString());return value;}).toList();
    }
}
