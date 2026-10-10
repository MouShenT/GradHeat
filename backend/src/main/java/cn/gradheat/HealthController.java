package cn.gradheat;

import java.util.Map;
import org.springframework.web.bind.annotation.*;

/** Liveness remains separate from publication readiness; no connection detail is returned. */
@RestController
@RequestMapping("/api/v1")
public class HealthController {
    private final PublicationRepository publications;
    public HealthController(PublicationRepository publications) {this.publications=publications;}
    @GetMapping("/health") public Map<String,Object> health() {
        boolean ready;
        try {publications.current();ready=true;}catch(RuntimeException unavailable){ready=false;}
        return Map.of("service","gradheat-business","live",true,"publication_ready",ready);
    }
}
