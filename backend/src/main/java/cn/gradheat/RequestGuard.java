package cn.gradheat;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Set;
import jakarta.servlet.*;
import jakarta.servlet.http.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
public class RequestGuard extends OncePerRequestFilter {
    private final String token;
    private final boolean publicWrite;
    public RequestGuard(@Value("${gradheat.api-token:}") String token,@Value("${gradheat.public-write-enabled:false}") boolean publicWrite) {this.token=token;this.publicWrite=publicWrite;}
    @Override protected void doFilterInternal(HttpServletRequest req,HttpServletResponse res,FilterChain chain) throws ServletException,IOException {
        res.setHeader("X-Content-Type-Options","nosniff");res.setHeader("Cache-Control","no-store");
        if(!req.getRequestURI().startsWith("/api/")) {chain.doFilter(req,res);return;}
        boolean mutation=!Set.of("GET","HEAD","OPTIONS").contains(req.getMethod());
        boolean collection=req.getRequestURI().startsWith("/api/v1/collection");
        boolean persistence=mutation && (collection || req.getRequestURI().startsWith("/api/v1/tasks") || req.getRequestURI().contains("/comparisons"));
        String supplied=req.getHeader("Authorization");
        boolean authorized=!token.isBlank() && supplied!=null && MessageDigest.isEqual(("Bearer "+token).getBytes(StandardCharsets.UTF_8),supplied.getBytes(StandardCharsets.UTF_8));
        String origin=req.getHeader("Origin"),host=req.getHeader("Host");
        boolean cross="cross-site".equals(req.getHeader("Sec-Fetch-Site"));
        if(origin!=null)try {cross |= !java.net.URI.create(origin).getAuthority().equals(host);}catch(Exception e){cross=true;}
        if(cross && !authorized) {deny(res,403,"cross_site","不接受跨站请求");return;}
        boolean local=Set.of("127.0.0.1","::1","0:0:0:0:0:0:0:1").contains(req.getRemoteAddr()) && Set.of("127.0.0.1","localhost","::1","[::1]").contains(req.getServerName());
        if(collection && !authorized && !(publicWrite && local)) {deny(res,403,"collection_disabled","采集控制仅向本机已启用的工作台开放");return;}
        if(persistence && !authorized && !publicWrite) {deny(res,403,"write_disabled","写入接口尚未启用授权");return;}
        int budget=collection?5_000_000:1_000_000;
        if(req.getContentLengthLong()>budget) {deny(res,413,"input_limit","请求超过输入预算");return;}
        if(mutation) {
            byte[] body=req.getInputStream().readNBytes(budget+1);
            if(body.length>budget) {deny(res,413,"input_limit","请求超过输入预算");return;}
            chain.doFilter(new BufferedRequest(req,body),res);
        } else chain.doFilter(req,res);
    }
    private void deny(HttpServletResponse res,int status,String code,String detail)throws IOException {res.setStatus(status);res.setContentType("application/json;charset=UTF-8");res.getWriter().write(Json.encode(java.util.Map.of("code",code,"detail",detail)));}
    private static class BufferedRequest extends HttpServletRequestWrapper {
        final byte[] body;
        BufferedRequest(HttpServletRequest request,byte[] body) {super(request);this.body=body;}
        @Override public int getContentLength() {return body.length;}
        @Override public long getContentLengthLong() {return body.length;}
        @Override public ServletInputStream getInputStream() {
            var input=new java.io.ByteArrayInputStream(body);
            return new ServletInputStream() {
                @Override public int read() {return input.read();}
                @Override public boolean isFinished() {return input.available()==0;}
                @Override public boolean isReady() {return true;}
                @Override public void setReadListener(ReadListener listener) {throw new IllegalStateException("Synchronous JSON body only");}
            };
        }
        @Override public java.io.BufferedReader getReader() {return new java.io.BufferedReader(new java.io.InputStreamReader(getInputStream(),StandardCharsets.UTF_8));}
    }
}
