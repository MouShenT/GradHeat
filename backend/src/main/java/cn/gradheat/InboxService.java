package cn.gradheat;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;

@Service
public class InboxService {
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    public InboxService(JdbcTemplate jdbc,TransactionTemplate tx) {this.jdbc=jdbc;this.tx=tx;}
    public String consume(String raw) {
        if(raw.length()>64000)throw new IllegalArgumentException("Event exceeds budget");
        JsonNode event=Json.parse(raw);
        PublicationRepository.rejectPrivate(event);
        String message=event.path("message_id").asString(), taskId=event.path("task_id").asString();
        TaskService.validateId(message);TaskService.validateId(taskId);
        String state=event.path("status").asString(),input=event.path("input_version").asString();
        int attempt=event.path("attempt").asInt(),sequence=event.path("sequence").asInt();
        if(event.path("schema_version").asInt()!=1 || !"task.status".equals(event.path("type").asString()) || !TaskService.STATUSES.contains(state) || sequence<1 || attempt<1 || !input.matches("[a-f0-9]{64}"))throw new IllegalArgumentException("Invalid event");
        String sha=Json.sha(raw);
        return tx.execute(s -> {
            var task=jdbc.queryForList("SELECT status,attempt,last_event_sequence,input_version,processor_version,cancel_requested FROM app_task WHERE task_id=? FOR UPDATE",taskId);
            if(task.isEmpty())throw new IllegalArgumentException("Unknown task");
            var prior=jdbc.queryForList("SELECT payload_sha FROM app_inbox WHERE message_id=?",message);
            if(!prior.isEmpty()) {if(!sha.equals(prior.getFirst().get("payload_sha")))throw new IllegalArgumentException("Message ID changed content");return "duplicate";}
            var current=task.getFirst();
            if(!input.equals(current.get("input_version")))throw new IllegalArgumentException("Wrong input version");
            if(!event.path("processor_version").asString().equals(current.get("processor_version")))throw new IllegalArgumentException("Wrong processor version");
            String disposition="applied";
            boolean stale=attempt!=((Number)current.get("attempt")).intValue() || sequence<=((Number)current.get("last_event_sequence")).intValue() || TaskService.STOPPED.contains(current.get("status"));
            if(stale)disposition="stale";
            if(!stale) {
                if("queued".equals(state))throw new IllegalArgumentException("Worker cannot move task back to queued");
                String resultId=event.path("result_id").isString()?event.path("result_id").asString():null;
                String resultSha=event.path("result_sha").isString()?event.path("result_sha").asString():null;
                String error=event.path("error_code").isString()?event.path("error_code").asString():null;
                if(error!=null && !error.matches("[a-zA-Z0-9_.-]{1,80}"))throw new IllegalArgumentException("Invalid error code");
                if("succeeded".equals(state)) {
                    TaskService.validateId(resultId);
                    if(resultSha==null || !resultSha.matches("[a-f0-9]{64}"))throw new IllegalArgumentException("Missing result SHA");
                    var results=jdbc.queryForList("SELECT r.result_sha,r.result_bytes,e.task_id,e.input_version,e.processor_version,e.attempt FROM python_worker_result r JOIN python_worker_execution e ON r.execution_key=e.execution_key WHERE r.result_id=?",resultId);
                    if(results.isEmpty())throw new IllegalStateException("Result not committed");
                    var stored=results.getFirst();
                    if(!resultSha.equals(stored.get("result_sha")) || !taskId.equals(stored.get("task_id")) || !input.equals(stored.get("input_version")) || !current.get("processor_version").equals(stored.get("processor_version")) || attempt!=((Number)stored.get("attempt")).intValue())throw new IllegalStateException("Result context differs");
                    byte[] bytes=(byte[])stored.get("result_bytes");
                    if(bytes==null || !Json.sha(bytes).equals(resultSha))throw new IllegalStateException("Result bytes invalid");
                }
                jdbc.update("UPDATE app_task SET status=?,last_event_sequence=?,result_id=?,result_sha=?,error_code=?,updated_at=? WHERE task_id=?",state,sequence,resultId,resultSha,error,Timestamp.from(Instant.now()),taskId);
            }
            jdbc.update("INSERT INTO app_inbox(message_id,task_id,payload_sha,payload_json,received_at,disposition) VALUES(?,?,?,?,?,?)",message,taskId,sha,raw,Timestamp.from(Instant.now()),disposition);
            return disposition;
        });
    }
}
