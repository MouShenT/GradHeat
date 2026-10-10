package cn.gradheat;

import java.sql.Timestamp;
import java.time.*;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class OutboxService {
    public record Pending(String messageId,String routingKey,String body,String leaseToken,int attempts) {}
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    public OutboxService(JdbcTemplate jdbc,TransactionTemplate tx) {this.jdbc=jdbc;this.tx=tx;}
    public Optional<Pending> claim() {
        return tx.execute(s -> {
            Timestamp now=Timestamp.from(Instant.now());
            var rows=jdbc.queryForList("SELECT message_id,routing_key,payload_json,attempts FROM app_outbox WHERE ((status='pending' AND next_attempt_at<=?) OR (status='publishing' AND lease_until<?)) ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED",now,now);
            if(rows.isEmpty())return Optional.empty();
            var row=rows.getFirst();String token=UUID.randomUUID().toString(),id=(String)row.get("message_id");
            jdbc.update("UPDATE app_outbox SET status='publishing',lease_token=?,lease_until=?,attempts=attempts+1 WHERE message_id=?",token,Timestamp.from(Instant.now().plusSeconds(30)),id);
            return Optional.of(new Pending(id,(String)row.get("routing_key"),(String)row.get("payload_json"),token,((Number)row.get("attempts")).intValue()+1));
        });
    }
    public boolean sent(Pending pending) {
        return jdbc.update("UPDATE app_outbox SET status='sent',sent_at=?,lease_token=NULL,lease_until=NULL,last_error=NULL WHERE message_id=? AND status='publishing' AND lease_token=?",Timestamp.from(Instant.now()),pending.messageId(),pending.leaseToken())==1;
    }
    public void failed(Pending pending,String safeCode) {
        if(!safeCode.matches("[a-z_.-]{1,80}"))throw new IllegalArgumentException();
        long delay=Math.min(300L,1L<<Math.min(pending.attempts(),8));
        jdbc.update("UPDATE app_outbox SET status='pending',next_attempt_at=?,lease_token=NULL,lease_until=NULL,last_error=? WHERE message_id=? AND status='publishing' AND lease_token=?",Timestamp.from(Instant.now().plusSeconds(delay)),safeCode,pending.messageId(),pending.leaseToken());
    }
}
