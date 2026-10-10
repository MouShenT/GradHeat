package cn.gradheat;

import com.sun.net.httpserver.HttpServer;
import java.net.*;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import java.util.concurrent.atomic.*;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.RANDOM_PORT,properties={
    "spring.datasource.url=jdbc:h2:mem:gradheat-http;MODE=MySQL;DB_CLOSE_DELAY=-1",
    "spring.datasource.driver-class-name=org.h2.Driver","spring.datasource.username=sa","spring.datasource.password=",
    "gradheat.messaging-enabled=false","gradheat.redis-enabled=false","gradheat.api-token=test-api-only",
    "gradheat.python-token=synthetic-internal-token-with-32-characters","gradheat.public-write-enabled=false"})
@DirtiesContext(classMode=DirtiesContext.ClassMode.AFTER_CLASS)
class BusinessHttpTest {
    @LocalServerPort int port;
    @Autowired JdbcTemplate jdbc;
    static final String PAYLOAD="{\"data_as_of\":\"2026-10-09\",\"programmes\":[],\"units\":[{\"name\":\"样本大学\"}]}";
    static final String VERSION=Json.sha(PAYLOAD);
    static HttpServer python;
    static AtomicReference<String> lastPath=new AtomicReference<>(),internalToken=new AtomicReference<>(),upgrade=new AtomicReference<>();
    static AtomicInteger calls=new AtomicInteger(),remoteStatus=new AtomicInteger(200);
    static final HttpClient CLIENT=HttpClient.newHttpClient();
    @DynamicPropertySource static void pythonService(DynamicPropertyRegistry registry) throws Exception {
        python=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        python.createContext("/internal/v1/",exchange->{
            calls.incrementAndGet();lastPath.set(exchange.getRequestURI().toString());internalToken.set(exchange.getRequestHeaders().getFirst("X-GradHeat-Internal-Token"));upgrade.set(exchange.getRequestHeaders().getFirst("Upgrade"));
            String body="{\"data_version\":\""+VERSION+"\",\"items\":[]}";
            if(exchange.getRequestURI().getPath().endsWith("/comparisons/evaluate"))body=packageJson();
            exchange.getRequestBody().readAllBytes();byte[] bytes=body.getBytes(StandardCharsets.UTF_8);exchange.getResponseHeaders().set("Content-Type","application/json");exchange.sendResponseHeaders(remoteStatus.get(),bytes.length);exchange.getResponseBody().write(bytes);exchange.close();
        });
        python.start();registry.add("gradheat.python-url",()->"http://127.0.0.1:"+python.getAddress().getPort());
    }
    @AfterAll static void stop() {python.stop(0);}
    @BeforeEach void schema() {
        calls.set(0);remoteStatus.set(200);lastPath.set(null);
        jdbc.execute("CREATE TABLE IF NOT EXISTS admissions_publication(version_id CHAR(64) PRIMARY KEY,payload_json CLOB)");
        jdbc.execute("CREATE TABLE IF NOT EXISTS admissions_head(name VARCHAR(32) PRIMARY KEY,version_id CHAR(64))");
        jdbc.execute("CREATE TABLE IF NOT EXISTS admissions_publication_bytes(version_id CHAR(64) PRIMARY KEY,content BLOB)");
        jdbc.execute("CREATE TABLE IF NOT EXISTS personal_comparison(comparison_id CHAR(64) PRIMARY KEY,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,title VARCHAR(120),data_version CHAR(64),analysis_version VARCHAR(80),candidate_count INT,result_json CLOB,report_md CLOB,result_bytes BLOB)");
        jdbc.update("DELETE FROM admissions_head");jdbc.update("DELETE FROM admissions_publication_bytes");jdbc.update("DELETE FROM admissions_publication");jdbc.update("DELETE FROM personal_comparison");
        jdbc.update("INSERT INTO admissions_publication VALUES(?,?)",VERSION,PAYLOAD);jdbc.update("INSERT INTO admissions_publication_bytes VALUES(?,?)",VERSION,PAYLOAD.getBytes(StandardCharsets.UTF_8));jdbc.update("INSERT INTO admissions_head VALUES('current',?)",VERSION);
    }
    static String packageJson() {
        String raw="{\"analysis_version\":\"test-v1\",\"cards\":[],\"data_version\":\""+VERSION+"\",\"input\":{\"title\":\"示例比较\"}}",report="# 示例比较\n";
        var value=Json.MAPPER.createObjectNode();value.set("result",Json.parse(raw));value.put("canonical_result",raw).put("canonical_archive",ComparisonArchive.archiveText(raw,report)).put("report_md",report).put("comparison_id",Json.sha(ComparisonArchive.archiveText(raw,report)));return Json.encode(value);
    }
    HttpResponse<String> call(String method,String path,String body,boolean token,String origin) throws Exception {
        var b=HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+path));
        if(token)b.header("Authorization","Bearer test-api-only");if(origin!=null)b.header("Origin",origin);
        if(body!=null)b.header("Content-Type","application/json").method(method,HttpRequest.BodyPublishers.ofString(body,StandardCharsets.UTF_8));else b.method(method,HttpRequest.BodyPublishers.noBody());
        return CLIENT.send(b.build(),HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
    }
    @Test void publicPublicationAndVersionDoNotInvokePython() throws Exception {
        var data=call("GET","/api/v1/admissions",null,false,null);assertEquals(200,data.statusCode());assertEquals(VERSION,data.headers().firstValue("X-Data-Version").orElseThrow());assertEquals("样本大学",Json.parse(data.body()).path("units").get(0).path("name").asString());assertEquals(0,calls.get());
        assertEquals(200,call("GET","/api/v1/version",null,false,null).statusCode());
    }
    @Test void collectionControlsRequireLocalWriteAuthorizationAndUseInternalBridge() throws Exception {
        assertEquals(403,call("POST","/api/v1/collection/browser","{}",false,null).statusCode());assertEquals(0,calls.get());
        assertEquals(200,call("POST","/api/v1/collection/browser","{}",true,null).statusCode());assertEquals("/internal/v1/collection/browser",lastPath.get());
        assertEquals(200,call("POST","/api/v1/collection/prepare","{\"tasks\":[{\"platform\":\"bili\",\"query\":\"合成查询\"}]}",true,null).statusCode());assertEquals("/internal/v1/collection/prepare",lastPath.get());
        int before=calls.get();assertEquals(404,call("GET","/api/v1/collection/batch-invalid",null,true,null).statusCode());assertEquals(before,calls.get());
        assertEquals(403,call("GET","/api/v1/collection/browser",null,false,null).statusCode());
        assertEquals(403,call("POST","/api/v1/collection/browser","{}",false,"https://outside.test").statusCode());
    }
    @Test void healthSeparatesProcessLivenessFromVerifiedPublicationReadiness() throws Exception {
        var ready=call("GET","/api/v1/health",null,false,null);assertEquals(200,ready.statusCode());assertTrue(Json.parse(ready.body()).path("live").asBoolean());assertTrue(Json.parse(ready.body()).path("publication_ready").asBoolean());
        jdbc.update("DELETE FROM admissions_head");var unavailable=call("GET","/api/v1/health",null,false,null);assertEquals(200,unavailable.statusCode());assertTrue(Json.parse(unavailable.body()).path("live").asBoolean());assertFalse(Json.parse(unavailable.body()).path("publication_ready").asBoolean());assertFalse(unavailable.body().contains("jdbc"));
    }
    @Test void vueProductionIndexIsServedFromPackagedStaticResources() throws Exception {
        var home=call("GET","/",null,false,null);assertEquals(200,home.statusCode());assertTrue(home.body().contains("id=\"app\""));assertTrue(home.body().contains("/assets/"));
    }
    @Test void staleVersionPreventsRemoteWork() throws Exception {
        var response=call("POST","/api/v1/recommendations","{\"data_version\":\""+"d".repeat(64)+"\"}",false,null);assertEquals(409,response.statusCode());assertEquals(0,calls.get());
        assertEquals(422,call("POST","/api/v1/game-scenario","{}",false,null).statusCode());
    }
    @Test void internalBridgeUsesTokenAndSanitizesFailure() throws Exception {
        var response=call("GET","/api/v1/dashboard",null,false,null);assertEquals(200,response.statusCode());assertEquals("/internal/v1/dashboard",lastPath.get());assertEquals("synthetic-internal-token-with-32-characters",internalToken.get());assertNull(upgrade.get(),"Internal uvicorn connection must stay HTTP/1.1 without h2c upgrade");
        remoteStatus.set(500);var failed=call("GET","/api/v1/dashboard",null,false,null);assertEquals(503,failed.statusCode());assertFalse(failed.body().contains("synthetic-internal"));
    }
    @Test void unknownHeatDoesNotCallWorkerAndChineseUnitIsEncoded() throws Exception {
        assertEquals(404,call("GET","/api/v1/heat?unit=unknown",null,false,null).statusCode());assertEquals(0,calls.get());
        assertEquals(200,call("GET","/api/v1/heat?unit="+URLEncoder.encode("样本大学",StandardCharsets.UTF_8),null,false,null).statusCode());assertTrue(lastPath.get().startsWith("/internal/v1/heat?unit="));
    }
    @Test void saveReadAndExportUsesImmutablePythonArchive() throws Exception {
        String input="{\"data_version\":\""+VERSION+"\"}";
        assertEquals(403,call("POST","/api/v1/admissions/comparisons",input,false,null).statusCode());assertEquals(0,calls.get());
        var saved=call("POST","/api/v1/admissions/comparisons",input,true,null);assertEquals(200,saved.statusCode());String id=Json.parse(saved.body()).path("comparison_id").asString();
        assertEquals(200,call("GET","/api/v1/admissions/comparisons/"+id,null,false,null).statusCode());
        var exported=call("GET","/api/v1/admissions/comparisons/"+id+"/export?format=md",null,false,null);assertEquals(200,exported.statusCode());assertEquals("# 示例比较\n",exported.body());assertTrue(exported.headers().firstValue("Content-Disposition").orElseThrow().contains(".md"));
    }
    @Test void crossSiteBrowserCannotReadOrPersist() throws Exception {
        assertEquals(403,call("GET","/api/v1/admissions",null,false,"https://untrusted.test").statusCode());
        assertEquals(403,call("POST","/api/v1/tasks","{}",false,"https://untrusted.test").statusCode());
        assertEquals(422,call("POST","/api/v1/tasks","{}",true,null).statusCode());
    }
}
