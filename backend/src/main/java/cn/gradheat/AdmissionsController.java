package cn.gradheat;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import tools.jackson.databind.JsonNode;

@RestController
@RequestMapping("/api/v1")
public class AdmissionsController {
    private final PublicationRepository publications;
    private final PythonBridge python;
    public AdmissionsController(PublicationRepository publications,PythonBridge python) { this.publications=publications;this.python=python; }
    @GetMapping("/admissions") public ResponseEntity<JsonNode> admissions() {
        var data=publications.current(); return ResponseEntity.ok().header("X-Data-Version",data.version()).body(data.payload());
    }
    @GetMapping("/version") public Map<String,Object> version() { var p=publications.current();return Map.of("data_version",p.version(),"data_as_of",p.payload().path("data_as_of").asString()); }
    @GetMapping("/institutions") public Map<String,Object> institutions() { return Map.of("items",publications.current().payload().path("units")); }
    @GetMapping("/dashboard") public JsonNode dashboard() { return python.get("/internal/v1/dashboard"); }
    @GetMapping("/heat") public JsonNode heat(@RequestParam String unit) {
        if(unit.length()>160 || unit.isBlank()) throw new IllegalArgumentException();
        boolean known=false; for(JsonNode u:publications.current().payload().path("units")) if(unit.equals(u.path("name").asString()))known=true;
        if(!known) {
            for(JsonNode u:python.get("/internal/v1/school-indices")) if(unit.equals(u.path("unit").asString()))known=true;
            if(!known) throw new ApiFailure(404,"unit_missing","招生单位不属于当前资料");
        }
        return python.get("/internal/v1/heat?unit="+URLEncoder.encode(unit,StandardCharsets.UTF_8));
    }
    @PostMapping("/recommendations") public JsonNode recommendations(@RequestBody JsonNode body) {
        ensureCurrent(body);return python.post("/internal/v1/recommendations",body);
    }
    @PostMapping({"/game-scenario","/scenarios"}) public JsonNode scenario(@RequestBody JsonNode body) { ensureCurrent(body);return python.post("/internal/v1/game-scenario",body); }
    @PostMapping("/victory-index") public JsonNode victory(@RequestBody JsonNode body) { ensureCurrent(body);return python.post("/internal/v1/victory-index",body); }
    @GetMapping("/school-dossier") public JsonNode school(@RequestParam String unit) {
        if(unit.isBlank() || unit.length()>160) throw new IllegalArgumentException();
        return python.get("/internal/v1/school-dossier?unit="+URLEncoder.encode(unit,StandardCharsets.UTF_8));
    }
    @GetMapping("/school-indices") public JsonNode schoolIndices() { return python.get("/internal/v1/school-indices"); }
    @PostMapping("/admissions/compare") public JsonNode compare(@RequestBody JsonNode body) {
        ensureCurrent(body);return python.post("/internal/v1/comparisons/evaluate",body).path("result");
    }
    void ensureCurrent(JsonNode body) {
        String requested=body.path("data_version").asString();
        if(!requested.matches("[0-9a-f]{64}")) throw new IllegalArgumentException("Invalid data version");
        if(!publications.current().version().equals(requested)) throw new ApiFailure(409,"stale_version","招生资料已更新，请刷新后重试");
    }
}
