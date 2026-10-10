package cn.gradheat;

import java.nio.charset.StandardCharsets;
import com.rabbitmq.client.Channel;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(name="gradheat.messaging-enabled",havingValue="true")
public class StatusListener {
    private final InboxService inbox;
    public StatusListener(InboxService inbox) {this.inbox=inbox;}
    @RabbitListener(queues="gradheat.task.status")
    public void status(Message message,Channel channel) throws Exception {
        long tag=message.getMessageProperties().getDeliveryTag();
        try {
            if(message.getBody().length>64000)throw new IllegalArgumentException("Event too large");
            inbox.consume(new String(message.getBody(),StandardCharsets.UTF_8));
            channel.basicAck(tag,false);
        } catch(DataAccessException transientFailure) {channel.basicNack(tag,false,true);}
        catch(RuntimeException malformed) {channel.basicReject(tag,false);}
    }
}
