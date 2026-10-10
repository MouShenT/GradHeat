package cn.gradheat;

public interface ConfirmedSender {
    void send(OutboxService.Pending pending) throws Exception;
}
