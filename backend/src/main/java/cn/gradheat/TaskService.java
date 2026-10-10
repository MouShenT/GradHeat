package cn.gradheat;

import java.sql.Timestamp;
import java.time.*;
import java.util.*;
import jakarta.validation.constraints.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;

@Service
public class TaskService {
    public static final Set<String> TYPES=Set.of("collect.official","collect.social.win-primary","collect.autonomous.win-primary","extract.documents","verify.information","analyse.long");
    public static final Set<String> STATUSES=Set.of("queued","running","paused_human","succeeded","failed","cancelled");
    public static final Set<String> STOPPED=Set.of("paused_human","succeeded","failed","cancelled");
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final PublicationRepository publications;
    public record Create(@NotBlank @Pattern(regexp="[0-9a-fA-F-]{36}") String request_id,
                         @NotBlank @Size(max=80) String type,
                         @Pattern(regexp="[0-9a-f]{64}") @NotNull String input_version,
                         @NotNull JsonNode scope, @Min(1) @Max(1440) Integer deadline_minutes) {}
    public TaskService(JdbcTemplate jdbc,TransactionTemplate tx,PublicationRepository publications) {this.jdbc=jdbc;this.tx=tx;this.publications=publications;}
    public Map<String,Object> create(Create request) {
        String taskId=UUID.fromString(request.request_id()).toString();
        if(!TYPES.contains(request.type()) || !request.scope().isObject() || Json.encode(request.scope()).length()>16000) throw new IllegalArgumentException("Task scope/type invalid");
        PublicationRepository.rejectPrivate(request.scope());
        if(!publications.current().version().equals(request.input_version())) throw new ApiFailure(409,"stale_version","创建任务前请刷新资料版本");
        String scope=Json.canonical(request.scope());
        String processor="gradheat-python-v1";
        Instant now=Instant.now(), deadline=now.plus(Duration.ofMinutes(request.deadline_minutes()==null?60:request.deadline_minutes()));
        return tx.execute(status -> {
            List<Map<String,Object>> prior=jdbc.queryForList("SELECT task_type,input_version,processor_version,scope_json FROM app_task WHERE task_id=? FOR UPDATE",taskId);
            if(!prior.isEmpty()) {
                var p=prior.getFirst();
                if(!request.type().equals(p.get("task_type")) || !request.input_version().equals(p.get("input_version")) || !scope.equals(Json.canonical(Json.parse((String)p.get("scope_json")))))
                    throw new ApiFailure(409,"request_reused","同一请求编号已用于不同任务");
                return Map.of("task_id",taskId,"reused",true,"status",get(taskId).get("status"));
            }
            jdbc.update("INSERT INTO app_task(task_id,task_type,input_version,processor_version,scope_json,status,created_at,updated_at,deadline_at) VALUES(?,?,?,?,?,'queued',?,?,?)",
                taskId,request.type(),request.input_version(),processor,scope,Timestamp.from(now),Timestamp.from(now),Timestamp.from(deadline));
            String messageId=UUID.randomUUID().toString();
            Map<String,Object> command=new LinkedHashMap<>();
            command.put("schema_version",1);command.put("message_id",messageId);command.put("task_id",taskId);command.put("type",request.type());
            command.put("input_version",request.input_version());command.put("processor_version",processor);command.put("scope",request.scope());
            command.put("trace_id",taskId);command.put("attempt",1);command.put("created_at",now.toString());command.put("deadline_at",deadline.toString());
            jdbc.update("INSERT INTO app_outbox(message_id,task_id,routing_key,payload_json,status,next_attempt_at,created_at) VALUES(?,?,?,?,'pending',?,?)",
                messageId,taskId,request.type(),Json.canonical(command),Timestamp.from(now),Timestamp.from(now));
            return Map.of("task_id",taskId,"status","queued","reused",false);
        });
    }
    public Map<String,Object> get(String taskId) {
        validateId(taskId);
        var rows=jdbc.queryForList("SELECT task_id,task_type,input_version,processor_version,status,attempt,last_event_sequence,cancel_requested,result_id,result_sha,error_code,created_at,updated_at,deadline_at FROM app_task WHERE task_id=?",taskId);
        if(rows.isEmpty())throw new ApiFailure(404,"task_missing","任务不存在");
        Map<String,Object> output=JdbcMaps.lower(rows.getFirst());
        output.put("type",output.remove("task_type"));
        for(String key:List.of("created_at","updated_at","deadline_at")) { Object value=output.get(key);if(value instanceof Timestamp t)output.put(key,t.toInstant().toString()); }
        return output;
    }
    public Map<String,Object> cancel(String taskId) {
        validateId(taskId);
        return tx.execute(s -> {
            var rows=jdbc.queryForList("SELECT status FROM app_task WHERE task_id=? FOR UPDATE",taskId);
            if(rows.isEmpty())throw new ApiFailure(404,"task_missing","任务不存在");
            if(!STOPPED.contains(rows.getFirst().get("status"))) {
                var active=jdbc.queryForList("SELECT status FROM app_outbox WHERE task_id=? AND status IN ('publishing','sent') FOR UPDATE",taskId);
                boolean notDispatched=active.isEmpty() && "queued".equals(rows.getFirst().get("status"));
                jdbc.update("UPDATE app_task SET cancel_requested=TRUE,status=?,updated_at=? WHERE task_id=?",notDispatched?"cancelled":rows.getFirst().get("status"),Timestamp.from(Instant.now()),taskId);
                jdbc.update("UPDATE app_outbox SET status='cancelled',lease_token=NULL,lease_until=NULL WHERE task_id=? AND status='pending'",taskId);
            }
            return get(taskId);
        });
    }
    public List<Map<String,Object>> list() {
        return jdbc.query("SELECT task_id FROM app_task ORDER BY created_at DESC LIMIT 100",(rs,n)->rs.getString(1)).stream().map(this::get).toList();
    }
    public JsonNode result(String taskId) {
        var task=get(taskId);
        if(!"analyse.long".equals(task.get("type")))throw new ApiFailure(403,"internal_task_result","采集与解析原件只供后台审核，不在数据页面返回");
        String scopeText=jdbc.queryForObject("SELECT scope_json FROM app_task WHERE task_id=?",String.class,taskId);
        if(!Set.of("recommendations","game-scenario","compare","dashboard","heat").contains(Json.parse(scopeText).path("operation").asString()))throw new ApiFailure(403,"internal_task_result","任务结果不属于公开分析资料");
        if(!"succeeded".equals(task.get("status")))throw new ApiFailure(409,"task_not_succeeded","任务尚无成功结果");
        var rows=jdbc.queryForList("SELECT result_bytes,result_sha FROM python_worker_result WHERE result_id=?",task.get("result_id"));
        if(rows.isEmpty() || !task.get("result_sha").equals(rows.getFirst().get("result_sha")))throw new ApiFailure(503,"result_integrity","结果档案需要复核");
        byte[] raw=(byte[])rows.getFirst().get("result_bytes");
        if(raw==null || !Json.sha(raw).equals(task.get("result_sha")))throw new ApiFailure(503,"result_integrity","结果档案需要复核");
        JsonNode payload=Json.parse(new String(raw,java.nio.charset.StandardCharsets.UTF_8));PublicationRepository.rejectPrivate(payload);return payload;
    }
    static void validateId(String id) { try {if(!UUID.fromString(id).toString().equals(id))throw new IllegalArgumentException();}catch(Exception e){throw new ApiFailure(404,"task_missing","任务不存在");} }
}
