/**
 * A group's face: its members' marks in a small stack, the way a chat app
 * shows a group before a group image exists. The room list and the panel head
 * share it so a room looks the same in both places.
 */
import { UsersRound } from 'lucide-react';
import { BotMark } from '@/components/bots/BotMark';
import type { RoomMemberInfo } from '@/api/rooms';
import './RoomAvatar.css';

export function RoomAvatar({
  members = [],
  size = 36,
}: {
  members?: RoomMemberInfo[];
  size?: number;
}): React.ReactElement {
  const shown = members.slice(0, 3);
  return (
    <span className="room-avatar" style={{ width: size, height: size }} aria-hidden>
      {shown.length === 0 ? (
        <span className="room-avatar__empty" style={{ width: size, height: size }}>
          <UsersRound className="h-1/2 w-1/2" aria-hidden />
        </span>
      ) : (
        shown.map((member, index) => (
          <span
            key={member.bot_id}
            className={`room-avatar__seat room-avatar__seat--${index}`}
            style={{ width: Math.round(size * 0.58), height: Math.round(size * 0.58) }}
          >
            <BotMark bot={member} size={Math.round(size * 0.58)} decorative />
          </span>
        ))
      )}
      {members.length > shown.length && (
        <span className="room-avatar__more">+{members.length - shown.length}</span>
      )}
    </span>
  );
}
