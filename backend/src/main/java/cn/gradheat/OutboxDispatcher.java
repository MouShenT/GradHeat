package cn.gradheat;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(name="gradheat.messaging-enabled",havingValue="true")
public class OutboxDispatcher {
    private final OutboxService outbox;
    private final ConfirmedSender sender;
    public OutboxDispatcher(OutboxService outbox,ConfirmedSender sender) {this.outbox=outbox;this.sender=sender;}
    @Scheduled(fixedDelayString="${gradheat.outbox-delay-ms:1000}")
    public void dispatch() {
        var pending=outbox.claim();if(pending.isEmpty())return;
        try {sender.send(pending.get());outbox.sent(pending.get());}
        catch(Exception e) {outbox.failed(pending.get(),"publish_unconfirmed");}
    }
}
