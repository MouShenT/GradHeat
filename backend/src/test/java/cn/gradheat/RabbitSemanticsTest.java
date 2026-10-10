package cn.gradheat;

import com.rabbitmq.client.Channel;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CompletableFuture;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.amqp.core.*;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class RabbitSemanticsTest {
    @Test void publisherRequiresAckAndNoReturn() throws Exception {
        var rabbit=mock(RabbitTemplate.class);var sender=new RabbitConfirmedSender(rabbit);
        var item=new OutboxService.Pending("id","analyse.long","{}","lease",1);
        doAnswer(a->{CorrelationData c=a.getArgument(3);c.getFuture().complete(new CorrelationData.Confirm(true,null));return null;}).when(rabbit).send(eq("gradheat.commands"),eq("analyse.long"),any(Message.class),any(CorrelationData.class));
        sender.send(item);verify(rabbit).setMandatory(true);
        doAnswer(a->{CorrelationData c=a.getArgument(3);c.setReturned(new ReturnedMessage(a.getArgument(2),312,"NO_ROUTE","gradheat.commands","analyse.long"));c.getFuture().complete(new CorrelationData.Confirm(true,null));return null;}).when(rabbit).send(eq("gradheat.commands"),eq("analyse.long"),any(Message.class),any(CorrelationData.class));
        assertThrows(IllegalStateException.class,()->sender.send(item));
    }
    @Test void listenerAcknowledgesOnlyAfterCommitAndRejectsPoison() throws Exception {
        var inbox=mock(InboxService.class);var listener=new StatusListener(inbox);var channel=mock(Channel.class);
        var props=new MessageProperties();props.setDeliveryTag(12);var message=new Message("{}".getBytes(StandardCharsets.UTF_8),props);
        when(inbox.consume("{}")).thenReturn("duplicate");listener.status(message,channel);
        var order=inOrder(inbox,channel);order.verify(inbox).consume("{}");order.verify(channel).basicAck(12,false);
        reset(channel);doThrow(new IllegalArgumentException()).when(inbox).consume("{}");listener.status(message,channel);verify(channel).basicReject(12,false);verify(channel,never()).basicAck(anyLong(),anyBoolean());
        reset(channel);doThrow(new org.springframework.dao.DataAccessResourceFailureException("network")).when(inbox).consume("{}");listener.status(message,channel);verify(channel).basicNack(12,false,true);
    }
}
