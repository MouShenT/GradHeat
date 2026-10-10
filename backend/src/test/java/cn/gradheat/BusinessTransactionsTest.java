package cn.gradheat;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.*;
import org.junit.jupiter.api.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class BusinessTransactionsTest {
    JdbcTemplate jdbc;
    TransactionTemplate tx;
    PublicationRepository publications;
    TaskService tasks;
    OutboxService outbox;
    InboxService inbox;
    String version;
    @BeforeEach void prepare() {
        var ds=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DB_CLOSE_DELAY=-1","sa","");
        jdbc=new JdbcTemplate(ds);tx=new TransactionTemplate(new DataSourceTransactionManager(ds));
        jdbc.execute("CREATE TABLE admissions_publication(version_id CHAR(64) PRIMARY KEY,payload_json CLOB)");
        jdbc.execute("CREATE TABLE admissions_head(name VARCHAR(32) PRIMARY KEY,version_id CHAR(64))");
        jdbc.execute("CREATE TABLE admissions_publication_bytes(version_id CHAR(64) PRIMARY KEY,content BLOB)");
        jdbc.execute("CREATE TABLE app_task(task_id CHAR(36) PRIMARY KEY,task_type VARCHAR(80),input_version CHAR(64),processor_version VARCHAR(80),scope_json CLOB,status VARCHAR(32),attempt INT DEFAULT 1,last_event_sequence INT DEFAULT 0,cancel_requested BOOLEAN DEFAULT FALSE,result_id CHAR(36),result_sha CHAR(64),error_code VARCHAR(80),created_at TIMESTAMP,updated_at TIMESTAMP,deadline_at TIMESTAMP)");
        jdbc.execute("CREATE TABLE app_outbox(message_id CHAR(36) PRIMARY KEY,task_id CHAR(36),routing_key VARCHAR(80),payload_json CLOB,status VARCHAR(16),attempts INT DEFAULT 0,next_attempt_at TIMESTAMP,lease_token CHAR(36),lease_until TIMESTAMP,last_error VARCHAR(80),created_at TIMESTAMP,sent_at TIMESTAMP)");
        jdbc.execute("CREATE TABLE app_inbox(message_id CHAR(36) PRIMARY KEY,task_id CHAR(36),payload_sha CHAR(64),payload_json CLOB,received_at TIMESTAMP,disposition VARCHAR(32))");
        jdbc.execute("CREATE TABLE python_worker_execution(execution_key CHAR(64) PRIMARY KEY,task_id CHAR(36),input_version CHAR(64),processor_version VARCHAR(80),attempt INT)");
        jdbc.execute("CREATE TABLE python_worker_result(result_id CHAR(36) PRIMARY KEY,execution_key CHAR(64),payload_json CLOB,result_bytes BLOB,result_sha CHAR(64))");
        jdbc.execute("CREATE TABLE personal_comparison(comparison_id CHAR(64) PRIMARY KEY,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,title VARCHAR(120),data_version CHAR(64),analysis_version VARCHAR(80),candidate_count INT,result_json CLOB,report_md CLOB,result_bytes BLOB)");
        String publication="{\"data_as_of\":\"2026-10-09\",\"programmes\":[],\"units\":[{\"name\":\"样本大学\"}]}";version=Json.sha(publication);
        jdbc.update("INSERT INTO admissions_publication VALUES(?,?)",version,publication);
        jdbc.update("INSERT INTO admissions_publication_bytes VALUES(?,?)",version,publication.getBytes(java.nio.charset.StandardCharsets.UTF_8));
        jdbc.update("INSERT INTO admissions_head VALUES('current',?)",version);
        publications=new PublicationRepository(jdbc,mock(org.springframework.data.redis.core.StringRedisTemplate.class),false);
        tasks=new TaskService(jdbc,tx,publications);outbox=new OutboxService(jdbc,tx);inbox=new InboxService(jdbc,tx);
    }
    String create() {return (String)tasks.create(new TaskService.Create(UUID.randomUUID().toString(),"analyse.long",version,Json.parse("{\"operation\":\"game-scenario\"}"),60)).get("task_id");}
    String event(String task,int sequence,String state) {
        var value=new LinkedHashMap<String,Object>();value.put("schema_version",1);value.put("message_id",UUID.randomUUID().toString());value.put("task_id",task);value.put("type","task.status");value.put("input_version",version);value.put("processor_version","gradheat-python-v1");value.put("attempt",1);value.put("sequence",sequence);value.put("status",state);
        return Json.canonical(value);
    }
    @Test void taskAndOutboxCommitTogetherAndRetryIsIdempotent() {
        var input=new TaskService.Create(UUID.randomUUID().toString(),"analyse.long",version,Json.parse("{\"operation\":\"recommendations\"}"),60);
        var created=tasks.create(input);assertEquals(false,created.get("reused"));assertEquals(true,tasks.create(input).get("reused"));
        assertEquals(1,jdbc.queryForObject("SELECT COUNT(*) FROM app_task",Integer.class));assertEquals(1,jdbc.queryForObject("SELECT COUNT(*) FROM app_outbox",Integer.class));
        var wrong=new TaskService.Create(input.request_id(),input.type(),version,Json.parse("{\"operation\":\"game-scenario\"}"),60);
        assertEquals(409,assertThrows(ApiFailure.class,()->tasks.create(wrong)).status);
        var message=Json.parse(jdbc.queryForObject("SELECT payload_json FROM app_outbox",String.class));assertEquals(created.get("task_id"),message.path("task_id").asString());assertEquals("gradheat-python-v1",message.path("processor_version").asString());
    }
    @Test void failedOutboxInsertRollsBackTask() {
        jdbc.execute("DROP TABLE app_outbox");assertThrows(org.springframework.dao.DataAccessException.class,this::create);
        assertEquals(0,jdbc.queryForObject("SELECT COUNT(*) FROM app_task",Integer.class));
    }
    @Test void publisherFailureLeavesPendingAndConfirmMarksSent() {
        create();new OutboxDispatcher(outbox,p->{throw new IllegalStateException("connection failed");}).dispatch();
        assertEquals("pending",jdbc.queryForObject("SELECT status FROM app_outbox",String.class));assertEquals("publish_unconfirmed",jdbc.queryForObject("SELECT last_error FROM app_outbox",String.class));
        jdbc.update("UPDATE app_outbox SET next_attempt_at=?",Timestamp.from(Instant.now().minusSeconds(1)));
        new OutboxDispatcher(outbox,p->{}).dispatch();assertEquals("sent",jdbc.queryForObject("SELECT status FROM app_outbox",String.class));assertEquals(2,jdbc.queryForObject("SELECT attempts FROM app_outbox",Integer.class));
    }
    @Test void expiredLeaseCanBeReclaimedButOldPublisherCannotMarkNewClaimSent() {
        create();var first=outbox.claim().orElseThrow();assertTrue(outbox.claim().isEmpty());
        jdbc.update("UPDATE app_outbox SET lease_until=?",Timestamp.from(Instant.now().minusSeconds(1)));
        var second=outbox.claim().orElseThrow();assertNotEquals(first.leaseToken(),second.leaseToken());assertFalse(outbox.sent(first));assertTrue(outbox.sent(second));
    }
    @Test void duplicateEventsAndOldSequenceCannotRegressTask() {
        String id=create(),started=event(id,1,"running");assertEquals("applied",inbox.consume(started));assertEquals("duplicate",inbox.consume(started));
        assertEquals("applied",inbox.consume(event(id,2,"paused_human")));assertEquals("stale",inbox.consume(event(id,3,"running")));
        assertEquals("paused_human",tasks.get(id).get("status"));assertEquals(3,jdbc.queryForObject("SELECT COUNT(*) FROM app_inbox",Integer.class));
    }
    @Test void successNeedsCommittedMatchingResultAndRollbackLeavesNoInbox() {
        String task=create(),resultId=UUID.randomUUID().toString(),resultRaw="{\"answer\":42}",resultSha=Json.sha(resultRaw);
        var node=Json.parse(event(task,2,"succeeded"));((tools.jackson.databind.node.ObjectNode)node).put("result_id",resultId).put("result_sha",resultSha);
        String raw=Json.encode(node);assertThrows(IllegalStateException.class,()->inbox.consume(raw));
        assertEquals("queued",tasks.get(task).get("status"));assertEquals(0,jdbc.queryForObject("SELECT COUNT(*) FROM app_inbox",Integer.class));
        jdbc.update("INSERT INTO python_worker_execution VALUES(?,?,?,?,?)","e".repeat(64),task,version,"gradheat-python-v1",1);
        jdbc.update("INSERT INTO python_worker_result VALUES(?,?,?,?,?)",resultId,"e".repeat(64),resultRaw,resultRaw.getBytes(java.nio.charset.StandardCharsets.UTF_8),resultSha);assertEquals("applied",inbox.consume(raw));assertEquals("succeeded",tasks.get(task).get("status"));assertEquals(42,tasks.result(task).path("answer").asInt());
        assertEquals("stale",inbox.consume(event(task,1,"running")));assertEquals("succeeded",tasks.get(task).get("status"));
    }
    @Test void changedMessageIdentityRejectedWithoutNewState() {
        String task=create(),raw=event(task,1,"running");inbox.consume(raw);
        var changed=(tools.jackson.databind.node.ObjectNode)Json.parse(raw);changed.put("status","failed").put("sequence",2);
        assertThrows(IllegalArgumentException.class,()->inbox.consume(Json.encode(changed)));assertEquals("running",tasks.get(task).get("status"));
    }
    @Test void cancelUnsentButRunningWaitsForWorker() {
        String queued=create();assertEquals("cancelled",tasks.cancel(queued).get("status"));assertTrue(outbox.claim().isEmpty());
        String running=create();var claim=outbox.claim().orElseThrow();outbox.sent(claim);inbox.consume(event(running,1,"running"));
        var requested=tasks.cancel(running);assertEquals(true,requested.get("cancel_requested"));assertEquals("running",requested.get("status"));
        inbox.consume(event(running,2,"cancelled"));assertEquals("cancelled",tasks.get(running).get("status"));
    }
    @Test void immutableComparisonPreservesPythonFloatBytesAndDetectsTampering() {
        String raw="{\"analysis_version\":\"test-v1\",\"cards\":[],\"data_version\":\""+version+"\",\"input\":{\"title\":\"含 中文\"},\"tiny\":1e-07,\"whole\":1.0}";
        String report="# 含 中文\n\n测试";String archive=ComparisonArchive.archiveText(raw,report),id=Json.sha(archive);
        var pack=Json.MAPPER.createObjectNode().set("result",Json.parse(raw));((tools.jackson.databind.node.ObjectNode)pack).put("canonical_result",raw).put("canonical_archive",archive).put("report_md",report).put("comparison_id",id);
        var store=new ComparisonArchive(jdbc,tx);assertEquals(false,store.save(pack).get("reused"));assertEquals(true,store.save(pack).get("reused"));assertEquals("含 中文",store.get(id).get("title"));
        assertArrayEquals(raw.getBytes(java.nio.charset.StandardCharsets.UTF_8),jdbc.queryForObject("SELECT result_bytes FROM personal_comparison",byte[].class));
        jdbc.update("UPDATE personal_comparison SET result_bytes=?", "{}".getBytes());assertEquals(409,assertThrows(ApiFailure.class,()->store.get(id)).status);
    }
    @Test void sourceBearingPublicationNeverReachesPublicApi() {
        String text="{\"units\":[],\"programmes\":[],\"source_url\":\"https://example.test\"}",hash=Json.sha(text);
        jdbc.update("UPDATE admissions_publication SET payload_json=?,version_id=?",text,hash);jdbc.update("UPDATE admissions_publication_bytes SET content=?,version_id=?",text.getBytes(java.nio.charset.StandardCharsets.UTF_8),hash);jdbc.update("UPDATE admissions_head SET version_id=?",hash);
        assertEquals("unsafe_projection",assertThrows(ApiFailure.class,publications::current).code);
    }
    @Test void collectionAndExtractionTaskResultsCannotExposeRawMaterials() {
        var created=tasks.create(new TaskService.Create(UUID.randomUUID().toString(),"extract.documents",version,Json.parse("{\"sha256\":\""+"a".repeat(64)+"\",\"format\":\"pdf\"}"),60));
        assertEquals("internal_task_result",assertThrows(ApiFailure.class,()->tasks.result((String)created.get("task_id"))).code);
        assertFalse(tasks.get((String)created.get("task_id")).containsKey("scope_json"));
        assertThrows(ApiFailure.class,()->PublicationRepository.rejectPrivate(Json.parse("{\"results\":[{\"local_path\":\"private-sample\"}]}")));
    }
    @Test void publicationHashChecksExactBytesAndProjectionUsesNumericMeaning() {
        String canonical="{\"programmes\":[],\"tiny\":1e-07,\"units\":[],\"whole\":1.0}",hash=Json.sha(canonical);
        jdbc.update("UPDATE admissions_publication SET payload_json=?,version_id=?","{\"programmes\":[],\"units\":[],\"whole\":1,\"tiny\":0.0000001}",hash);
        jdbc.update("UPDATE admissions_publication_bytes SET content=?,version_id=?",canonical.getBytes(java.nio.charset.StandardCharsets.UTF_8),hash);jdbc.update("UPDATE admissions_head SET version_id=?",hash);
        assertEquals(hash,publications.current().version());
        jdbc.update("UPDATE admissions_publication SET payload_json=?","{\"programmes\":[],\"units\":[],\"whole\":2,\"tiny\":0.0000001}");
        assertEquals("publication_integrity",assertThrows(ApiFailure.class,publications::current).code);
        jdbc.update("UPDATE admissions_publication_bytes SET content=?","{}".getBytes());
        assertEquals("publication_integrity",assertThrows(ApiFailure.class,publications::current).code);
    }
}
