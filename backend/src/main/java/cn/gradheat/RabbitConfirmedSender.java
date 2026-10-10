package cn.gradheat;

import java.nio.charset.StandardCharsets;
import java.util.concurrent.TimeUnit;
import org.springframework.amqp.core.*;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(name="gradheat.messaging-enabled",havingValue="true")
public class RabbitConfirmedSender implements ConfirmedSender {
    private final RabbitTemplate rabbit;
    public RabbitConfirmedSender(RabbitTemplate rabbit) {this.rabbit=rabbit;this.rabbit.setMandatory(true);}
    @Override public void send(OutboxService.Pending pending) throws Exception {
        MessageProperties props=new MessageProperties();props.setContentType("application/json");props.setContentEncoding("UTF-8");props.setDeliveryMode(MessageDeliveryMode.PERSISTENT);props.setMessageId(pending.messageId());
        CorrelationData correlation=new CorrelationData(pending.messageId());
        rabbit.send("gradheat.commands",pending.routingKey(),new Message(pending.body().getBytes(StandardCharsets.UTF_8),props),correlation);
        var confirm=correlation.getFuture().get(5,TimeUnit.SECONDS);
        if(!confirm.ack() || correlation.getReturned()!=null)throw new IllegalStateException("Broker did not accept a routed command");
    }
}
