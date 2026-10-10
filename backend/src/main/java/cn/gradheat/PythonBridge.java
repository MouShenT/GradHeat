package cn.gradheat;

import java.net.*;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;

@Service
public class PythonBridge {
    private final String base,token;
    private final HttpClient client;
    public PythonBridge(@Value("${gradheat.python-url}") String base,@Value("${gradheat.python-token:}") String token) {
        URI uri=URI.create(base);
        if(!SetSupport.allowed(uri)) throw new IllegalArgumentException("Python URL must be a configured HTTP(S) service URL");
        this.base=base.replaceAll("/+$",""); this.token=token;
        client=HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).connectTimeout(Duration.ofSeconds(3)).followRedirects(HttpClient.Redirect.NEVER).build();
    }
    public JsonNode get(String path) { return request(path,null); }
    public JsonNode post(String path,JsonNode body) { return request(path,body); }
    public HttpResponse<java.io.InputStream> download(String path){
        if(!path.matches("/internal/v1/collection/batch-[0-9]{8}-[a-f0-9]{12}/download/(incomplete|handoff)"))throw new IllegalArgumentException("Unknown collection download");
        var request=HttpRequest.newBuilder(URI.create(base+path)).timeout(Duration.ofSeconds(30)).header("X-GradHeat-Internal-Token",token).GET().build();
        try {
            var response=client.send(request,HttpResponse.BodyHandlers.ofInputStream());
            if(response.statusCode()!=200){response.body().close();throw new ApiFailure(404,"download_missing","结果文件尚未生成");}
            return response;
        }catch(ApiFailure e){throw e;}catch(Exception e){throw new ApiFailure(503,"download_unavailable","文件暂时无法下载");}
    }
    private JsonNode request(String path,JsonNode body) {
        if(!path.startsWith("/internal/v1/")) throw new IllegalArgumentException("Unsupported internal route");
        HttpRequest.Builder builder=HttpRequest.newBuilder(URI.create(base+path)).timeout(Duration.ofSeconds(20)).header("Accept","application/json");
        if(!token.isBlank()) builder.header("X-GradHeat-Internal-Token",token);
        if(body!=null) builder.header("Content-Type","application/json").POST(HttpRequest.BodyPublishers.ofString(Json.encode(body),StandardCharsets.UTF_8));
        else builder.GET();
        try {
            var response=client.send(builder.build(),HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if(response.body().length()>8_000_000) throw new ApiFailure(502,"python_response_limit","计算结果超过响应预算");
            if(response.statusCode()>=400) {
                int code=(response.statusCode()==409 || response.statusCode()==422 || response.statusCode()==404)?response.statusCode():503;
                throw new ApiFailure(code,"python_rejected",code==409?"资料已更新，请刷新后重试":"计算服务暂不可用或输入条件不满足");
            }
            JsonNode value=Json.parse(response.body());
            PublicationRepository.rejectPrivate(value);
            return value;
        } catch(ApiFailure e) { throw e; }
        catch(InterruptedException e) { Thread.currentThread().interrupt(); throw new ApiFailure(503,"python_interrupted","计算请求中断"); }
        catch(Exception e) { throw new ApiFailure(503,"python_unavailable","计算服务暂不可用，请稍后重试"); }
    }
    private static class SetSupport {
        static boolean allowed(URI uri) { return ("http".equals(uri.getScheme()) || "https".equals(uri.getScheme())) && uri.getHost()!=null && uri.getUserInfo()==null && uri.getQuery()==null && uri.getFragment()==null; }
    }
}
